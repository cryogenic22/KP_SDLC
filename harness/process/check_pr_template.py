#!/usr/bin/env python3
"""PR template lint — the check the CI quality workflow's `process` job runs.

The PR template (.github/PULL_REQUEST_TEMPLATE.md) promises in its header
comment that five sections are required: Spec, Summary, Risk and invariants,
Verification, Self-review. This script is what makes that promise real. The
workflow injects the PR body via the PR_BODY env var (injection-safe: Python reads
the environment, nothing is shell-interpolated) and runs:

    python .github/scripts/check_pr_template.py

Checks, in document order of the required sections:
  * each required section exists as an h2 heading (case-insensitive
    prefix match, so `## Self-review (Tier 2 red flags)` counts);
  * each section has real content — after dropping blank lines, unchecked
    checkboxes, and ellipsis-only bullets, at least MIN_CONTENT_CHARS
    non-whitespace characters remain (presence, not prose quality);
  * Risk and invariants has four filled fields: change risk, invariants,
    known-pattern sweep, and negative proof;
  * Verification additionally carries at least one checked box `- [x]`
    (a claim of verification with nothing checked is vacuous).

HTML comments are stripped first so the template's own instructional
comment can never satisfy a check. Stripping matches GitHub's rendering:
a comment ends at `-->` or, if unterminated, at end of document — so an
unclosed `<!--` (which makes the PR render blank) cannot pass either.

Exit codes: 0 = pass; 1 = violations (listed on stdout, deterministic
order); 2 = PR_BODY env var missing — a workflow wiring error, kept
distinct so misconfiguration can't masquerade as a pass or a lint-fail.

Zero dependencies — Python stdlib only.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple

# The exact section list the template's header comment promises. Keep as a
# module-level tuple: the engine-side coupling test asserts every name here
# appears as an h2 heading in PULL_REQUEST_TEMPLATE.md.tmpl.
RISK_SECTION = "Risk and invariants"
REQUIRED: Tuple[str, ...] = (
    "Spec",
    "Summary",
    RISK_SECTION,
    "Verification",
    "Self-review",
)
RISK_FIELDS: Tuple[str, ...] = (
    "Change risk",
    "Invariants",
    "Known-pattern sweep",
    "Negative proof",
)

# A section is "filled" when at least this many non-whitespace characters
# survive placeholder stripping. Deliberately a presence floor, not an NLP
# judgment — see the tests before tuning it.
MIN_CONTENT_CHARS = 20

# GitHub ends an HTML comment at `-->` OR at end of document (CommonMark
# HTML block type 2 / HTML5 eof-in-comment) and drops it when rendering, so
# an unterminated `<!--` swallows the entire rest of the body. Strip with
# the same semantics or a blank-rendering PR body would pass the gate.
_HTML_COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_CHECKED_BOX_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.MULTILINE)
_UNCHECKED_BOX_RE = re.compile(r"^\s*[-*]\s*\[\s*\]")
_ELLIPSIS_BULLET_RE = re.compile(r"^-\s*(\.\.\.|…)\s*$")


_WHITESPACE_RE = re.compile(r"\s+")
_BULLET_PREFIX_RE = re.compile(r"^\s*[-*]\s+")
_RISK_LEVEL_RE = re.compile(r"^(?:low|medium|high)\s*[-:]\s*\S", re.IGNORECASE)
_PATTERN_ID_RE = re.compile(r"\bKP-RV-\d{3}\b", re.IGNORECASE)
_REASONED_ABSENCE_RE = re.compile(r"^(?:none|n/a)\s*[-:]\s*\S", re.IGNORECASE)

_RISK_PLACEHOLDER_FRAGMENTS = (
    "low | medium | high",
    "list the properties",
    "list applicable",
    "cite the planted",
)


def heading_matches(heading: str, required: str) -> bool:
    """Does an h2 heading satisfy a required-section name?

    Case-insensitive prefix match after whitespace normalization, so
    `Self-review (Tier 2 red flags)` satisfies `Self-review`. Exposed so the
    coupling test uses the checker's own semantics, not a reimplementation.
    """
    return heading.strip().lower().startswith(required.strip().lower())


def _split_sections(body: str) -> List[Tuple[str, str]]:
    """Split a comment-stripped body into (h2 heading, section text) pairs
    in document order. Text before the first h2 belongs to no section."""
    sections: List[Tuple[str, str]] = []
    current: Optional[str] = None
    buf: List[str] = []
    for line in body.split("\n"):
        m = _H2_RE.match(line)
        if m:
            if current is not None:
                sections.append((current, "\n".join(buf)))
            current = m.group(1)
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections.append((current, "\n".join(buf)))
    return sections


def _content_chars(section_text: str) -> int:
    """Count non-whitespace characters that are real content: blank lines,
    unchecked checkboxes, and ellipsis-only bullets don't count."""
    total = 0
    for line in section_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _UNCHECKED_BOX_RE.match(stripped):
            continue
        if _ELLIPSIS_BULLET_RE.match(stripped):
            continue
        total += len(_WHITESPACE_RE.sub("", stripped))
    return total


def _risk_field_values(section_text: str) -> dict[str, str]:
    """Return recognized risk-field values from Markdown bullet lines."""
    expected = {name.lower(): name for name in RISK_FIELDS}
    values: dict[str, str] = {}
    for line in section_text.split("\n"):
        item = _BULLET_PREFIX_RE.sub("", line)
        item = item.replace("**", "").replace("__", "")
        label, separator, value = item.partition(":")
        canonical = expected.get(label.strip().lower())
        if separator and canonical and canonical not in values:
            values[canonical] = value.strip()
    return values


def _real_risk_value(name: str, value: str) -> bool:
    compact = _WHITESPACE_RE.sub("", value)
    lowered = value.lower()
    if (
        len(compact) < 8
        or lowered in {"none", "n/a", "...", "tbd"}
        or re.search(r"<[^>]+>", value)
    ):
        return False
    if any(fragment in lowered for fragment in _RISK_PLACEHOLDER_FRAGMENTS):
        return False
    reasoned_absence = bool(_REASONED_ABSENCE_RE.match(value))
    if name == "Change risk":
        return bool(_RISK_LEVEL_RE.match(value))
    if name == "Known-pattern sweep":
        return bool(_PATTERN_ID_RE.search(value) or reasoned_absence)
    if name == "Negative proof" and lowered.startswith(("none", "n/a")):
        return reasoned_absence
    return True


def _invalid_risk_fields(section_text: str) -> List[str]:
    values = _risk_field_values(section_text)
    return [
        name
        for name in RISK_FIELDS
        if not _real_risk_value(name, values.get(name, ""))
    ]


def check_body(body: str) -> List[str]:
    """Pure check: return violation strings for a PR body, empty if clean.

    Deterministic — violations come out in the document order of REQUIRED,
    at most one per section (missing beats empty beats unchecked-box).
    """
    stripped = _HTML_COMMENT_RE.sub("", body)
    sections = _split_sections(stripped)

    violations: List[str] = []
    for name in REQUIRED:
        matched = next(
            (text for heading, text in sections if heading_matches(heading, name)),
            None,
        )
        if matched is None:
            violations.append(f"missing required section '## {name}'")
            continue
        if _content_chars(matched) < MIN_CONTENT_CHARS:
            violations.append(
                f"section '## {name}' is empty or placeholder-only "
                f"(needs at least {MIN_CONTENT_CHARS} characters of real content)"
            )
            continue
        if name == RISK_SECTION:
            invalid = _invalid_risk_fields(matched)
            if invalid:
                violations.append(
                    f"section '## {name}' has missing or placeholder fields: "
                    f"{', '.join(invalid)}"
                )
                continue
        if name == "Verification" and not _CHECKED_BOX_RE.search(matched):
            violations.append(
                f"section '## {name}' has no checked box - "
                f"check at least one '- [x]' item you actually did"
            )
    return violations


def main() -> int:
    """Thin env + exit-code wrapper around check_body."""
    if "PR_BODY" not in os.environ:
        print(
            "check_pr_template: PR_BODY is not set - the workflow must inject "
            "the PR body via `env: PR_BODY: ${{ github.event.pull_request.body }}`. "
            "This is a wiring error, not a template violation.",
            file=sys.stderr,
        )
        return 2

    violations = check_body(os.environ["PR_BODY"])
    if violations:
        for violation in violations:
            print(f"PR template: {violation}")
        print(f"PR template: {len(violations)} violation(s) - fill the required "
              f"sections ({', '.join(REQUIRED)}) in the PR description")
        return 1

    print("PR template: all required sections present and filled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
