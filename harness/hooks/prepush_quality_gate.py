#!/usr/bin/env python
"""PreToolUse pre-push quality gate — run the QG baseline ratchet before a
model-driven ``git push`` and DENY the push if it would go red in CI.

Why (self-healing harness): the QG baseline ratchet is a subtle, fast check
that is easy to skip locally — a push can go red on ``warnings N > baselined M``
after only the unit suites were run (this happened; see the friction log). This
hook mirrors CI's ``make check`` at push time, avoiding the round-trip to a red
CI run.

Scope: it intercepts the Bash TOOL only, so it gates the MODEL's pushes and
never the human's manual terminal pushes.

Contract (Claude Code PreToolUse hook), wired from .claude/settings.json as::

    {"matcher": "Bash", "hooks": [{"type": "command",
     "command": "python -P harness/hooks/prepush_quality_gate.py", "timeout": 60}]}

  * stdin: JSON {tool_name, tool_input:{command}, cwd, ...} (utf-8).
  * allow: exit 0 + empty stdout (normal permission flow proceeds).
  * deny:  exit 0 + stdout {"hookSpecificOutput": {"hookEventName":
    "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": ...}}.

Fail-open policy (a deliberate asymmetry from the DENY it can emit): it DENIES
only when QG completed a real scan and REPORTED failure (exit 1, valid JSON,
``passed == false``, files scanned > 0). A QG crash also exits 1, so exit 1
without a parseable verdict — or a zero-file scan, or any other exit code, or a
malformed hook input — ALLOWS. A broken/empty QG must never wedge every push;
CI stays the backstop.

Non-push commands and non-Bash tools pass through instantly (no QG run).

CLI fallback (no hook runner needed)::

    python prepush_quality_gate.py --check-command "git push origin main"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("prepush_quality_gate")

# A `git push` invocation at a command boundary, tolerating the prefixes a model
# actually emits: unquoted env-assignments (`FOO=bar git push`), a `sudo`/`env`
# wrapper, a path prefix (`/usr/bin/git push`), git global options (some take a
# value: `-c k=v`, `-C dir`), and a metachar terminator (`git push; echo x`).
# Rejects look-alikes (`git log --grep=push`, `echo git push`). Known gap: an
# env value with quoted whitespace (`X='a b' git push`) is not matched — rare,
# and CI is the backstop.
_GIT_PUSH_RE = re.compile(
    r"""(?:^|[\n;&|(`]|&&|\|\|)      # command boundary
        \s*
        (?:\w+=\S*\s+)*              # env-var assignments (unquoted values)
        (?:sudo\s+|env\s+)?          # a wrapper
        (?:\S*[/\\])?                # optional path prefix before 'git'
        git(?:\.exe)?
        \s+
        (?:-{1,2}\S+(?:\s+\S+)?\s+)* # git global options (some take a value)
        push(?![\w-])                # the 'push' subcommand, not 'pushup'
    """,
    re.VERBOSE,
)

_QG_REL = "quality-gate/quality_gate.py"
_BASELINE_REL = ".quality-gate.baseline.json"
_QG_TIMEOUT_S = 45
_MAX_LISTED = 8
# QG's synthesized ratchet-violation rules — surfaced in the deny message rather
# than the (baselined, tolerated) raw code findings that `issues` also lists.
_RATCHET_RULES = {"baseline_ratchet", "prs_score", "new_subfloor_file"}


def is_git_push(command: str) -> bool:
    """True iff ``command`` invokes ``git push`` in any simple command — catches
    env/path/sudo prefixes and metachar-terminated forms, rejects look-alikes."""
    return bool(command) and _GIT_PUSH_RE.search(command) is not None


def _json_or_none(text: str) -> dict | None:
    """Parse ``text`` as a JSON object, or None (with a debug log) on failure."""
    try:
        parsed = json.loads(text)
    except ValueError:
        logger.debug("QG stdout was not parseable JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _summarize(data: dict) -> str:
    """A compact human summary of why QG's check failed — the ratchet signals if
    present, else a pointer to ``make check``."""
    signals = [i for i in data.get("issues", []) if i.get("rule") in _RATCHET_RULES]
    listed = [
        f'  [{i.get("rule", "?")}] {i.get("message", "")}'
        for i in signals[:_MAX_LISTED]
    ]
    if listed:
        return "QG --mode check would fail CI:\n" + "\n".join(listed)
    return f"QG --mode check failed (PRS={data.get('prs')}). Run `make check` for the findings."


def verdict_for(returncode: int, stdout: str) -> tuple[str, str]:
    """Map a QG ``--mode check`` result to (verdict, detail):
      'pass'  — exit 0.
      'block' — exit 1 AND QG completed a real scan and reported failure
                (parseable JSON, files_checked > 0, ``passed`` is false).
      'skip'  — everything else. A QG CRASH also exits 1, so exit 1 without a
                parseable verdict (or a zero-file scan, or any other exit code)
                is treated as infrastructure and FAILS OPEN — a broken/empty QG
                must never wedge every push; CI stays the backstop.
    """
    if returncode == 0:
        return "pass", ""
    if returncode != 1:
        return "skip", f"QG exited {returncode} (infrastructure, not a violation)"
    data = _json_or_none(stdout)
    if data is None or "passed" not in data:
        return "skip", "QG exit 1 without a parseable verdict (crash?) — failing open"
    if int(data.get("stats", {}).get("files_checked", 0) or 0) == 0:
        return "skip", "QG scanned zero files — failing open"
    if data.get("passed"):
        return "pass", ""
    return "block", _summarize(data)


def _resolve_root(start: Path) -> Path | None:
    """Walk up from ``start`` to the dir holding BOTH QG and its baseline, so a
    push from a subdirectory is still gated; None if not found (→ fail open)."""
    start = Path(start).resolve()
    for base in (start, *start.parents):
        if (base / _QG_REL).exists() and (base / _BASELINE_REL).exists():
            return base
    return None


def run_gate(start: Path) -> tuple[str, str]:
    """Run the QG baseline ratchet against the repo containing ``start``; fail
    open ('skip') if the repo/QG/baseline can't be found or QG cannot run.

    (No ``--sarif``: unlike CI's ``make check`` it only writes an extra file and
    does not change the exit code, so gate and CI agree on the verdict while the
    push hook leaves no artifact in the working tree.)"""
    root = _resolve_root(start)
    if root is None:
        return "skip", "no QG + baseline found from cwd upward — failing open"
    try:
        proc = subprocess.run(
            [sys.executable, str(root / _QG_REL), "--root", str(root),
             "--mode", "check", "--baseline", str(root / _BASELINE_REL), "--json"],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=_QG_TIMEOUT_S, cwd=str(root),
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("QG subprocess did not run: %s", exc)
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


def decide(event: dict) -> dict | None:
    """The pure hook decision: a deny-payload dict to block, or None to allow."""
    if event.get("tool_name") != "Bash":
        return None
    command = (event.get("tool_input") or {}).get("command", "")
    if not is_git_push(command):
        return None
    verdict, detail = run_gate(Path(event.get("cwd") or "."))
    return _deny_payload(detail) if verdict == "block" else None


def _read_event() -> dict:
    """Parse the PreToolUse JSON object from stdin ('{}' if empty)."""
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-push QG gate (PreToolUse hook).")
    parser.add_argument("--check-command", help="Diagnose a command without stdin.")
    args = parser.parse_args(argv)

    if args.check_command is not None:
        push = is_git_push(args.check_command)
        verdict, detail = run_gate(Path.cwd()) if push else ("n/a", "not a git push")
        print(f"git push: {push} | verdict: {verdict}")
        if detail:
            print(detail)
        return 0

    try:
        decision = decide(_read_event())
    except Exception as exc:  # noqa: BLE001 — a hook must never wedge the tool
        logger.debug("prepush gate errored, failing open: %s", exc)
        return 0
    if decision is not None:
        print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
