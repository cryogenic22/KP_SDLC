#!/usr/bin/env python3
"""PR template lint — the check the CI quality workflow's `process` job runs.

The PR template (.github/PULL_REQUEST_TEMPLATE.md) promises in its header
comment that four sections are required: Spec, Summary, Verification,
Self-review. This script is what makes that promise real. The workflow
injects the PR body via the PR_BODY env var (injection-safe: Python reads
the environment, nothing is shell-interpolated) and runs:

    python .github/scripts/check_pr_template.py

Checks, in document order of the required sections:
  * each required section exists as an h2 heading (case-insensitive
    prefix match, so `## Self-review (Tier 2 red flags)` counts);
  * each section has real content — after dropping blank lines, unchecked
    checkboxes, and ellipsis-only bullets, at least MIN_CONTENT_CHARS
    non-whitespace characters remain (presence, not prose quality);
  * Verification additionally carries at least one checked box `- [x]`
    (a claim of verification with nothing checked is vacuous).

HTML comments are stripped first so the template's own instructional
comment can never satisfy a check.

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
REQUIRED: Tuple[str, ...] = ("Spec", "Summary", "Verification", "Self-review")

# A section is "filled" when at least this many non-whitespace characters
# survive placeholder stripping. Deliberately a presence floor, not an NLP
# judgment — see the tests before tuning it.
MIN_CONTENT_CHARS = 20

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_CHECKED_BOX_RE = re.compile(r"^\s*[-*]\s*\[[xX]\]", re.MULTILINE)
_UNCHECKED_BOX_RE = re.compile(r"^\s*[-*]\s*\[\s*\]")
_ELLIPSIS_BULLET_RE = re.compile(r"^-\s*(\.\.\.|…)\s*$")


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
        total += len(re.sub(r"\s+", "", stripped))
    return total


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
