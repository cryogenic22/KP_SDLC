#!/usr/bin/env python3
"""Scan the exact release file set for content that must not be published.

Issue #39: the source tree tracked raw CtxPack session artifacts, so the release
archive would have published operational memory — machine-specific absolute
paths, verbatim user prompts, cross-repository working context — rather than
only product source. No credential was involved; the problem is unclassified
personal/operational context in a public artifact.

Removing those files fixes today. This scanner is what stops tomorrow: it reads
the blob content of every path `git archive <rev>` would emit, from git rather
than from the working tree, so it scans what would actually ship.

**The detector has its own positive control.** While investigating #39 a scan
reported a clean tree because its own regex was wrong — a shell-escaped
``C:\\\\Users\\\\`` reached grep as ``C:\\Users\\`` where ``\\U`` silently
degraded to a literal, so the pattern matched nothing and the absence of
findings read as safety. `selftest()` therefore asserts every rule matches a
known positive and rejects a known negative, and the test suite runs it before
trusting any scan result. A privacy scanner that cannot fail is worse than none,
because it manufactures confidence.

Usage:
    python harness/selfci/release_privacy.py [--rev HEAD] [--json]

Exit codes: 0 clean, 1 findings, 2 usage/git error.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Placeholder identities that are documentation, not someone's machine.
PLACEHOLDER_USERS = frozenset({
    "user", "username", "youruser", "your-user", "me", "runner", "root",
    "home", "example", "someone", "<user>", "USERNAME",
})

_WINDOWS_USER = re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}([A-Za-z0-9_.-]+)")
_POSIX_HOME = re.compile(r"/home/([a-z][a-z0-9_.-]*)/")
_MAC_HOME = re.compile(r"/Users/([A-Za-z][A-Za-z0-9_.-]*)/")
_USER_HOME_PATTERNS = (_WINDOWS_USER, _POSIX_HOME, _MAC_HOME)

_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sk-prefixed provider key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}")),
    ("github fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")),
    ("aws secret", re.compile(r"aws_secret_access_key\s*[=:]\s*\S{20,}", re.I)),
)

# Path shapes that are local operational memory or local build output. These are
# judged by path, not content: a raw session record is out of scope for a public
# artifact even when it happens to contain nothing sensitive.
_LOCAL_ONLY_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw ctx session record", re.compile(r"^\.claude/ctx/.*\.ctx$")),
    ("ctx session gist", re.compile(r"^\.claude/ctx/.*gist\.md$")),
    ("ctx session ledger", re.compile(r"^\.claude/ctx/(?!public/).*\.jsonl$")),
    ("local agent output", re.compile(r"^Claude outputs?/")),
    ("local scan output", re.compile(r"^\.quality-reports/")),
)

# Reviewed exceptions, scoped to one rule per path rather than muting a file
# wholesale. Empty on purpose. An entry would be a decision that a specific path
# may carry a specific shape, and it belongs in review because this file is a
# protected surface.
#
# The detector's own fixtures need no entry: every sample in `selftest()` is
# assembled at runtime from fragments, so no flaggable literal appears in this
# file's source. That is deliberate — an allowlist covering the scanner's own
# source is precisely the entry that would later be widened to cover a real leak.
ALLOW: dict[str, frozenset[str]] = {}


@dataclass(frozen=True)
class Finding:
    path: str
    rule: str
    detail: str
    line: int

    def as_dict(self) -> dict:
        return {"path": self.path, "rule": self.rule,
                "detail": self.detail, "line": self.line}


def release_paths(rev: str, root: Path = REPO_ROOT) -> list[str]:
    """Exactly the paths `git archive <rev>` emits."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", rev],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-tree failed for {rev}: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def blob(rev: str, path: str, root: Path = REPO_ROOT) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{rev}:{path}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cannot read {rev}:{path}")
    return proc.stdout


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _line_number(offsets: list[int], position: int) -> int:
    """1-based line for a character offset, via bisect over line starts."""
    return bisect.bisect_right(offsets, position)


def _credential_findings(path: str, text: str, offsets: list[int]) -> list[Finding]:
    findings: list[Finding] = []
    for label, pattern in _CREDENTIAL_PATTERNS:
        for match in pattern.finditer(text):
            # The label, never the matched secret, reaches the report.
            findings.append(
                Finding(path, "credential", label,
                        _line_number(offsets, match.start())))
    return findings


def _user_path_findings(path: str, text: str, offsets: list[int]) -> list[Finding]:
    findings: list[Finding] = []
    for pattern in _USER_HOME_PATTERNS:
        for match in pattern.finditer(text):
            who = match.group(1)
            if who.lower() in PLACEHOLDER_USERS:
                continue
            findings.append(
                Finding(path, "absolute-user-path", f"home directory of {who!r}",
                        _line_number(offsets, match.start())))
    return findings


def scan_text(path: str, text: str) -> list[Finding]:
    """Every content rule, applied once over the whole text.

    Pattern-major rather than line-major: each compiled pattern sweeps the text
    once and line numbers come from a bisect over line starts, so adding a rule
    costs one pass rather than one pass per line.
    """
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return (_credential_findings(path, text, offsets)
            + _user_path_findings(path, text, offsets))


def scan_path(path: str) -> list[Finding]:
    for label, pattern in _LOCAL_ONLY_PATHS:
        if pattern.search(path):
            return [Finding(path, "local-only-artifact", label, 0)]
    return []


def scan(rev: str = "HEAD", root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in release_paths(rev, root):
        allowed = ALLOW.get(path, frozenset())
        findings.extend(f for f in scan_path(path) if f.rule not in allowed)
        data = blob(rev, path, root)
        if _is_binary(data):
            continue
        text = data.decode("utf-8", errors="replace")
        findings.extend(f for f in scan_text(path, text) if f.rule not in allowed)
    return findings


def _fixtures() -> dict[str, list]:
    """Detector fixtures, assembled from fragments.

    Nothing here is a literal: written as one, this file's own source would trip
    its own rules, and the only remedies would be an allowlist over the scanner
    or a weaker rule — both worse than the awkwardness of concatenation.
    """
    bs = chr(92)
    who = "ali" + "ce"
    return {
        "content_positive": [
            ("absolute-user-path", "see C:" + bs + "Users" + bs + who + bs + "x"),
            ("absolute-user-path", "cd C:/" + "Users/" + who + "/Documents"),
            ("absolute-user-path", "log at /ho" + "me/" + who + "/app.log"),
            ("absolute-user-path", "open /Us" + "ers/" + who.title() + "/Lib/x"),
            ("credential", "token = " + "sk-" + "A" * 24),
            ("credential", "GH=" + "ghp_" + "b" * 24),
            ("credential", "key " + "AKIA" + "A" * 16),
            ("credential", "-----BEGIN RSA " + "PRIVATE KEY" + "-----"),
            ("credential", "xox" + "b-" + "1" * 14),
        ],
        "content_negative": [
            "a normal sentence about /ho" + "me directories in general",
            "install to C:" + bs + "Users" + bs + "<user>" + bs + "AppData",
            "the runner home is /ho" + "me/runner/work and that is CI",
            "sk-" + "not-a-key",
            "relative path .claude/ctx/public/decisions.md",
        ],
        "path_positive": [
            ".claude/ctx/session-abc123" + ".ctx",
            ".claude/ctx/latest-" + "gist.md",
            ".claude/ctx/checkpoints" + ".jsonl",
            "Claude out" + "puts/report.html",
        ],
        "path_negative": [
            ".claude/settings.json",
            ".claude/ctx/public/decisions.jsonl",
            "docs/install.md",
            "harness/skills/review-convergence/SKILL.md",
        ],
    }


def _rules_hit(sample: str) -> list[str]:
    return [f.rule for f in scan_text("probe.txt", sample)]


def _check_content_rules(fixtures: dict[str, list]) -> list[str]:
    failures: list[str] = []
    for rule, sample in fixtures["content_positive"]:
        if rule not in _rules_hit(sample):
            failures.append(f"rule {rule!r} did not match its positive sample")
    for sample in fixtures["content_negative"]:
        hits = _rules_hit(sample)
        if hits:
            failures.append(f"false positive on {sample!r}: {hits}")
    return failures


def _check_path_rules(fixtures: dict[str, list]) -> list[str]:
    expected = ([(s, True) for s in fixtures["path_positive"]]
                + [(s, False) for s in fixtures["path_negative"]])
    failures: list[str] = []
    for sample, should_flag in expected:
        if bool(scan_path(sample)) != should_flag:
            verb = "missed" if should_flag else "false positive on"
            failures.append(f"path rule {verb} {sample!r}")
    return failures


def selftest() -> list[str]:
    """Prove every rule can fire and can stay silent; empty means it works."""
    fixtures = _fixtures()
    return _check_content_rules(fixtures) + _check_path_rules(fixtures)


def _report(findings: list[Finding]) -> str:
    if not findings:
        return "[release-privacy] clean — nothing flagged in the release file set."
    by_path: dict[str, list[Finding]] = {}
    for finding in findings:
        by_path.setdefault(finding.path, []).append(finding)
    lines = [f"[release-privacy] {len(findings)} finding(s) "
             f"across {len(by_path)} file(s):"]
    for path in sorted(by_path):
        items = by_path[path]
        count = len(items)
        rules = sorted({f.rule for f in items})
        lines.append(f"  {path}  ({count} hit(s): {', '.join(rules)})")
        for finding in items[:3]:
            where = f"line {finding.line}" if finding.line else "path"
            lines.append(f"      {where}: {finding.rule} — {finding.detail}")
        if count > 3:
            lines.append(f"      ... and {count - 3} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="revision to scan")
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--selftest-only", action="store_true")
    args = parser.parse_args(argv)

    failures = selftest()
    if failures:
        for failure in failures:
            print(f"[release-privacy] DETECTOR BROKEN: {failure}", file=sys.stderr)
        return 2
    if args.selftest_only:
        print("[release-privacy] detector self-test passed")
        return 0

    try:
        findings = scan(args.rev, Path(args.root).resolve())
    except RuntimeError as exc:
        print(f"[release-privacy] {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps({"rev": args.rev, "clean": not findings,
                          "findings": [f.as_dict() for f in findings]}, indent=2))
    else:
        print(_report(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
