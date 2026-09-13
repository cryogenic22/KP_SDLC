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

# Windows and macOS compare paths case-insensitively, so a lower-cased drive
# path and a title-cased one name the same home directory and must be detected
# identically. Linux is case-sensitive, so `/home/` stays literal there and only
# the account name widens.
#
# No example is spelled out here on purpose. The first draft of this comment
# carried two, and they were real enough that this file's own scanner flagged
# its own source the moment the rules below became case-insensitive — caught by
# `test_release_tree_is_clean` in CI. Examples live in `_fixtures()`, assembled
# from fragments.
_WINDOWS_USER = re.compile(
    r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}([A-Za-z0-9_.-]+)", re.I)
_POSIX_HOME = re.compile(r"/home/([A-Za-z][A-Za-z0-9_.-]*)/")
# The lookbehind is what makes the case-insensitive form safe: `/users/` is an
# extremely common REST route, and without it `GET /api/users/alice` would be
# reported as someone's home directory. An absolute home path begins at a path
# root, never in the middle of a longer path segment.
_MAC_HOME = re.compile(r"(?<![A-Za-z0-9_./-])/Users/([A-Za-z][A-Za-z0-9_.-]*)/", re.I)
_USER_HOME_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows user home", _WINDOWS_USER),
    ("linux home", _POSIX_HOME),
    ("mac user home", _MAC_HOME),
)

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
#
# Matched case-insensitively: the repository is authored on Windows, whose
# filesystem is case-insensitive, so the same file can reach the index as
# `.claude/ctx/x.ctx` or `.Claude/CTX/x.CTX`. A case-sensitive path rule would
# let the second spelling ship.
_LOCAL_ONLY_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("raw ctx session record", re.compile(r"^\.claude/ctx/.*\.ctx$", re.I)),
    ("ctx session gist", re.compile(r"^\.claude/ctx/.*gist\.md$", re.I)),
    ("ctx session ledger",
     re.compile(r"^\.claude/ctx/(?!public/).*\.jsonl$", re.I)),
    ("local agent output", re.compile(r"^Claude outputs?/", re.I)),
    ("local scan output", re.compile(r"^\.quality-reports/", re.I)),
)

# How far into a blob a NUL byte is looked for. A NUL means the file is not
# provably plain text, which is a reportable state rather than a reason to stop
# scanning it — see `_decodings` and the `unscannable-content` rule.
_BINARY_PROBE = 8192

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


def has_nul(data: bytes) -> bool:
    """True when the blob is not provably plain text."""
    return b"\x00" in data[:_BINARY_PROBE]


def _decodings(data: bytes) -> list[str]:
    """Every text view of a blob that is worth scanning.

    A NUL byte used to end the scan for that file, which made it the cheapest
    possible bypass: one NUL anywhere in the first 8 KiB and the credential and
    home-path rules never ran. They run now.

    UTF-16 is the reason one view is not enough. It is the canonical
    NUL-carrying text encoding, and decoding it as UTF-8 interleaves a NUL
    through every word, so `sk-AAAA...` becomes `s\\x00k\\x00-\\x00A...` and no
    content rule can match it. The extra views cost nothing on ordinary files,
    which never reach them.
    """
    views = [data.decode("utf-8", errors="replace")]
    if not has_nul(data):
        return views
    for codec in ("utf-16-le", "utf-16-be"):
        decoded = _try_decode(data, codec)
        if decoded is not None:
            views.append(decoded)
    return views


def _try_decode(data: bytes, codec: str) -> str | None:
    """Decode under `codec`, or None when the blob is not that encoding.

    The failure is a fact about the blob, not an error to swallow: a blob that
    is not UTF-16 simply has no UTF-16 view, and the caller still scans the
    UTF-8 view and still reports the file as unscannable.
    """
    try:
        return data.decode(codec)
    except (UnicodeDecodeError, ValueError):
        return None


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
    for _label, pattern in _USER_HOME_PATTERNS:
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


def scan_blob(path: str, data: bytes) -> list[Finding]:
    """Every finding for one blob's content, across all of its text views.

    A NUL-carrying blob yields an `unscannable-content` finding *in addition to*
    whatever the content rules match, because a passing content scan over a
    replace-decoded binary proves nothing about the bytes it mangled. The
    release set carries no binary today, so this costs nothing until someone
    adds one — at which point it is a reviewed `ALLOW` entry, not a silent pass.
    """
    findings: list[Finding] = []
    if has_nul(data):
        findings.append(Finding(
            path, "unscannable-content",
            "NUL bytes: content is not provably text", 0))
    for text in _decodings(data):
        findings.extend(scan_text(path, text))
    return list(dict.fromkeys(findings))


def scan(rev: str = "HEAD", root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for path in release_paths(rev, root):
        allowed = ALLOW.get(path, frozenset())
        candidates = scan_path(path) + scan_blob(path, blob(rev, path, root))
        findings.extend(f for f in candidates if f.rule not in allowed)
    return findings


def _content_detectors() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Every detector `scan_text` applies, as (label, pattern)."""
    return _CREDENTIAL_PATTERNS + _USER_HOME_PATTERNS


# Fixture fragments. Nothing in this file is written as a flaggable literal:
# written as one, this file's own source would trip its own rules, and the only
# remedies would be an allowlist over the scanner or a weaker rule — both worse
# than the awkwardness of concatenation.
_BS = chr(92)
_WHO = "ali" + "ce"


def _content_fixtures() -> dict[str, str]:
    """One positive per content detector, keyed by that detector's own label.

    Keyed by label rather than listed by rule name because a rule name is not a
    detector: seven distinct patterns all report `credential`, so a list keyed
    by rule let one matching pattern vouch for all seven.
    """
    return {
        "sk-prefixed provider key": "token = " + "sk-" + "A" * 24,
        "github token": "GH=" + "ghp_" + "b" * 24,
        "github fine-grained token": "PAT " + "github" + "_pat_" + "c" * 24,
        "aws access key id": "key " + "AKIA" + "A" * 16,
        "slack token": "hook " + "xox" + "b-" + "1" * 14,
        "private key block": "-----BEGIN RSA " + "PRIVATE KEY" + "-----",
        "aws secret": "aws" + "_secret_access_key" + " = " + "d" * 24,
        # Deliberately lower-cased: on Windows and macOS these spell the same
        # directories as their title-cased forms.
        "windows user home": "see C:" + _BS + "users" + _BS + _WHO + _BS + "x",
        "linux home": "log at /ho" + "me/" + _WHO + "/app.log",
        "mac user home": "open /us" + "ers/" + _WHO.title() + "/Lib/x",
    }


def _path_fixtures() -> dict[str, str]:
    """One positive per path detector, keyed by that detector's own label."""
    return {
        "raw ctx session record": ".claude/ctx/session-abc123" + ".ctx",
        "ctx session gist": ".claude/ctx/latest-" + "gist.md",
        "ctx session ledger": ".claude/ctx/checkpoints" + ".jsonl",
        "local agent output": "Claude out" + "puts/report.html",
        "local scan output": ".quality-re" + "ports/report.json",
    }


def _fixtures() -> dict[str, object]:
    """Every self-test sample: positives per detector, plus the negatives."""
    return {
        "content": _content_fixtures(),
        "path": _path_fixtures(),
        "path_case_variants": [
            ".Claude/CTX/session-abc123" + ".CTX",
            "CLAUDE OUT" + "PUTS/report.html",
            ".Quality-Re" + "ports/report.json",
        ],
        "content_negative": [
            "a normal sentence about /ho" + "me directories in general",
            "install to C:" + _BS + "Users" + _BS + "<user>" + _BS + "AppData",
            "the runner home is /ho" + "me/runner/work and that is CI",
            "sk-" + "not-a-key",
            "relative path .claude/ctx/public/decisions.md",
            # The route, not a home directory — locks the `_MAC_HOME` lookbehind.
            "GET /api/us" + "ers/" + _WHO + "/profile returns 200",
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


def _uncovered(detectors: tuple[tuple[str, re.Pattern[str]], ...],
               samples: dict[str, str], kind: str) -> list[str]:
    """Detectors with no positive fixture, and fixtures naming no detector.

    This is the check that makes the rest of the self-test non-vacuous. Without
    it, `github fine-grained token`, `aws secret` and `local scan output`
    shipped with no positive control at all while the self-test reported green.
    A detector added without a fixture now fails the gate.
    """
    labels = {label for label, _ in detectors}
    covered = set(samples)
    return ([f"{kind} detector {label!r} has no positive fixture"
             for label in sorted(labels - covered)]
            + [f"{kind} fixture {label!r} names no detector"
               for label in sorted(covered - labels)])


def _check_own_positive(detectors: tuple[tuple[str, re.Pattern[str]], ...],
                        samples: dict[str, str], kind: str) -> list[str]:
    """Each fixture must be matched by the detector it is named for."""
    by_label = dict(detectors)
    return [f"{kind} detector {label!r} did not match its own positive sample"
            for label, sample in sorted(samples.items())
            if label in by_label and not by_label[label].search(sample)]


def _check_content_rules(fixtures: dict) -> list[str]:
    detectors = _content_detectors()
    samples: dict[str, str] = fixtures["content"]
    failures = (_uncovered(detectors, samples, "content")
                + _check_own_positive(detectors, samples, "content"))
    for sample in fixtures["content_negative"]:
        hits = _rules_hit(sample)
        if hits:
            failures.append(f"false positive on {sample!r}: {hits}")
    return failures


def _check_path_rules(fixtures: dict) -> list[str]:
    samples: dict[str, str] = fixtures["path"]
    failures = (_uncovered(_LOCAL_ONLY_PATHS, samples, "path")
                + _check_own_positive(_LOCAL_ONLY_PATHS, samples, "path"))
    for variant in fixtures["path_case_variants"]:
        if not scan_path(variant):
            failures.append(f"path rule is case-sensitive: missed {variant!r}")
    for benign in fixtures["path_negative"]:
        if scan_path(benign):
            failures.append(f"path rule false positive on {benign!r}")
    return failures


def _check_blob_rules() -> list[str]:
    """A NUL byte must report the file, not silence the content rules."""
    failures: list[str] = []
    secret = "token = " + "sk-" + "E" * 24
    laced = ("note" + chr(0) + secret).encode("utf-8")
    rules = {f.rule for f in scan_blob("probe.bin", laced)}
    if "unscannable-content" not in rules:
        failures.append("NUL-carrying blob was not reported as unscannable")
    if "credential" not in rules:
        failures.append("a NUL byte still suppresses the content rules")
    if "credential" not in {f.rule for f in
                            scan_blob("wide.txt", secret.encode("utf-16-le"))}:
        failures.append("UTF-16 content is not scanned")
    if scan_blob("clean.txt", b"nothing to see here"):
        failures.append("false positive on an ordinary text blob")
    return failures


def selftest() -> list[str]:
    """Prove every detector can fire and can stay silent; empty means it works.

    Covers three properties, not one: every detector has its own positive
    control, every detector stays silent on its negatives, and no encoding or
    letter-case spelling of a flagged thing escapes the scan.
    """
    fixtures = _fixtures()
    return (_check_content_rules(fixtures) + _check_path_rules(fixtures)
            + _check_blob_rules())


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
