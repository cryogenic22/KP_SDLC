#!/usr/bin/env python
"""PreToolUse pre-push quality gate — run the QG baseline ratchet before a
model-driven ``git push`` and DENY the push if it would go red in CI.

Why (self-healing harness): the QG baseline ratchet is a subtle, fast check
that is easy to skip locally — a push can go red on ``warnings N > baselined M``
after only the unit suites were run (this happened; see the friction log). This
hook mirrors CI's ``make check`` step at push time, so the round-trip to a red
CI run is avoided.

Scope: it intercepts the Bash TOOL only, so it gates the MODEL's pushes and
never the human's manual terminal pushes.

Contract (Claude Code PreToolUse hook), wired from .claude/settings.json as::

    {"matcher": "Bash", "hooks": [{"type": "command",
     "command": "python -P harness/hooks/prepush_quality_gate.py", "timeout": 60}]}

  * stdin: JSON {tool_name, tool_input:{command}, cwd, ...} — read as utf-8
    (Windows consoles default to cp1252).
  * allow: exit 0 + empty stdout (normal permission flow proceeds).
  * deny:  exit 0 + stdout {"hookSpecificOutput": {"hookEventName":
    "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": ...}}.

Fail-open policy (a deliberate asymmetry from the DENY it can emit): it DENIES
only on a genuine QG ratchet violation (QG exits 1 with findings). On ANY
infrastructure problem — QG or the baseline absent, QG crash/timeout, an
unexpected exit code, or malformed hook input — it ALLOWS. A broken local QG
must never wedge every push; CI stays the backstop.

Non-push commands and non-Bash tools pass through instantly (no QG run).

CLI fallback (vendor-neutral, no hook runner needed)::

    python prepush_quality_gate.py --check-command "git push origin main"
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# A `git push` subcommand, allowing global options (`-C dir`, `--no-pager`),
# anchored at a command boundary so `git log --grep=push` and `echo git push`
# (git not at a boundary) do not trip it.
_GIT_PUSH_RE = re.compile(
    r"(?:^|[\n;&|(]|&&|\|\|)\s*git\s+(?:-{1,2}\S+(?:\s+\S+)?\s+)*push(?:\s|$)"
)

_QG_REL = "quality-gate/quality_gate.py"
_BASELINE_REL = ".quality-gate.baseline.json"
_QG_TIMEOUT_S = 45
_MAX_LISTED = 8


def is_git_push(command: str) -> bool:
    """True iff ``command`` invokes ``git push`` as a subcommand (not merely
    mentions the word 'push')."""
    return bool(_GIT_PUSH_RE.search(command or ""))


def _summarize(stdout: str) -> str:
    """A compact human summary of the blocking QG findings (best-effort)."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return "QG baseline ratchet failed — run `make check` to see the findings."
    errors = [i for i in data.get("issues", []) if i.get("severity") == "error"]
    listed = [
        f'  {i.get("file", "?")}:{i.get("line", "?")} '
        f'[{i.get("rule", "?")}] {i.get("message", "")}'
        for i in errors[:_MAX_LISTED]
    ]
    head = f"{len(errors)} blocking QG finding(s)"
    return head + (":\n" + "\n".join(listed) if listed else ".")


def verdict_for(returncode: int, stdout: str) -> tuple[str, str]:
    """Map a QG ``--mode check`` exit code to (verdict, detail):
      'pass'  — exit 0: nothing to block.
      'block' — exit 1: a real ratchet/finding violation (detail = summary).
      'skip'  — any other code (argparse/config error, crash): fail open.
    """
    if returncode == 0:
        return "pass", ""
    if returncode == 1:
        return "block", _summarize(stdout)
    return "skip", f"QG exited {returncode} (infrastructure, not a quality violation)"


def run_gate(root: Path) -> tuple[str, str]:
    """Run the QG baseline ratchet against ``root``; fail open ('skip') if QG or
    the baseline is absent or QG cannot run."""
    qg, baseline = root / _QG_REL, root / _BASELINE_REL
    if not qg.exists() or not baseline.exists():
        return "skip", "QG or baseline not present in this repo"
    try:
        proc = subprocess.run(
            [sys.executable, str(qg), "--root", str(root), "--mode", "check",
             "--baseline", str(baseline), "--json"],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=_QG_TIMEOUT_S, cwd=str(root),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return "skip", f"QG did not run ({type(exc).__name__}) — failing open"
    return verdict_for(proc.returncode, proc.stdout or "")


def _deny_payload(detail: str) -> dict:
    """The PreToolUse deny decision blocking the push, with a fix-forward hint."""
    reason = (
        "Pre-push quality gate BLOCKED this push: the QG baseline ratchet would "
        "fail in CI.\n" + detail + "\n\nFix the findings (or re-baseline "
        "deliberately with `--mode baseline`), then push again. This gate runs "
        "only against the Bash tool — a genuine emergency can push from a terminal."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _read_event() -> dict:
    """Parse the PreToolUse JSON from stdin ('{}' on any read/parse problem)."""
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decide(event: dict) -> dict | None:
    """The pure hook decision: deny-payload dict to block, or None to allow."""
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command", "")
    if not is_git_push(command):
        return None
    verdict, detail = run_gate(Path(event.get("cwd") or "."))
    return _deny_payload(detail) if verdict == "block" else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-push QG gate (PreToolUse hook).")
    parser.add_argument("--check-command", help="Diagnose a command without stdin.")
    args = parser.parse_args(argv)

    if args.check_command is not None:
        verdict, detail = ("n/a", "not a git push")
        if is_git_push(args.check_command):
            verdict, detail = run_gate(Path.cwd())
        print(f"git push: {is_git_push(args.check_command)} | verdict: {verdict}")
        if detail:
            print(detail)
        return 0

    decision = decide(_read_event())
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
