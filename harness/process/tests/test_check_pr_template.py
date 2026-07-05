"""Tests for check_pr_template: the PR-body lint the CI `process` job runs.

The shipped workflow (harness/ci/quality.yml.tmpl, `process` job) invokes
`python .github/scripts/check_pr_template.py` with the PR body injected via
the PR_BODY env var. The checker enforces the contract the PR template's
header comment promises: required sections Spec, Summary, Verification,
Self-review must be present *and filled*, and Verification must carry at
least one checked box.

TDD: written before check_pr_template.py exists, so the import fails (RED).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_pr_template import (
    MIN_CONTENT_CHARS,
    REQUIRED,
    check_body,
    heading_matches,
    main,
)

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "templates"
    / "PULL_REQUEST_TEMPLATE.md.tmpl"
)

FULL_BODY = """\
## Spec

Implements specs/0042-pr-template-lint; satisfies acceptance criteria AC1 and AC3.

## Summary

- Added the PR template checker script that the CI process job invokes.
- Wired the FILE_MAP entry so born repos receive it at .github/scripts/.

## Verification

- [x] Tests added or updated (harness/process/tests/test_check_pr_template.py)
- [ ] Manual check (not needed for this change)

## Self-review (Tier 2 red flags)

- PASS: walked all 22 items, no red flags apply to this change.
"""

GUTTED_BODY = """\
## Spec

## Summary

## Verification

## Self-review
"""


def _without_section(body: str, heading: str) -> str:
    """Drop one `## heading` section (heading line + body) from a markdown body."""
    lines = body.split("\n")
    out: list[str] = []
    skipping = False
    for line in lines:
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            skipping = m.group(1).startswith(heading)
        if not skipping:
            out.append(line)
    return "\n".join(out)


def test_full_filled_body_passes():
    """A realistic filled PR body (all 4 sections, one checked box) is clean."""
    assert check_body(FULL_BODY) == []
    saved = os.environ.get("PR_BODY")
    os.environ["PR_BODY"] = FULL_BODY
    try:
        assert main() == 0
    finally:
        if saved is None:
            del os.environ["PR_BODY"]
        else:
            os.environ["PR_BODY"] = saved


def test_missing_required_section_fails():
    """A body lacking ## Verification gets a violation naming that section."""
    body = _without_section(FULL_BODY, "Verification")
    violations = check_body(body)
    assert violations, "expected a violation for the missing Verification section"
    assert any("Verification" in v for v in violations), violations
    assert not any("Spec" in v or "Summary" in v or "Self-review" in v for v in violations), (
        f"only Verification should be flagged, got: {violations}"
    )


def test_gutted_body_fails():
    """THE anti-case: all four headings present but every body empty must fail
    with one violation per empty section — a green here would be vacuous."""
    violations = check_body(GUTTED_BODY)
    assert len(violations) == len(REQUIRED), (
        f"expected one violation per empty section, got: {violations}"
    )
    for name in REQUIRED:
        assert any(name in v for v in violations), (
            f"no violation names empty section '{name}': {violations}"
        )


def test_unedited_template_verbatim_fails():
    """The exact shipped template text (placeholder bullets, all boxes
    unchecked) must not pass — at minimum Verification has no checked box."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    violations = check_body(text)
    assert violations, "unedited template passed the checker — vacuous gate"
    assert any("Verification" in v and "check" in v.lower() for v in violations), (
        f"expected a Verification checked-box violation, got: {violations}"
    )


def test_html_comments_stripped_before_matching():
    """Required-section names appearing only inside <!-- --> comments (e.g.
    the template's own header comment) must not count as present."""
    body = """\
<!--
Required sections: Spec, Summary, Verification, Self-review.
## Spec
## Summary
## Verification
## Self-review
This comment alone must never satisfy the checker.
-->
"""
    violations = check_body(body)
    assert len(violations) == len(REQUIRED), violations
    for v in violations:
        assert "missing" in v.lower(), f"expected 'missing' violations, got: {violations}"


def test_self_review_heading_matched_by_prefix():
    """`## Self-review (Tier 2 red flags)` satisfies the Self-review
    requirement — prefix match after normalization, case-insensitive."""
    assert heading_matches("Self-review (Tier 2 red flags)", "Self-review")
    assert heading_matches("self-REVIEW (tier 2)", "Self-review")
    assert not heading_matches("Review notes", "Self-review")
    # FULL_BODY uses the parenthesized heading; no Self-review violation appears.
    assert not any("Self-review" in v for v in check_body(FULL_BODY))


def test_verification_requires_checked_box():
    """Verification with prose but zero `- [x]` fails; one checked box passes."""
    prose = "\nRan the full local suite plus a manual smoke pass; all green.\n"
    unchecked = FULL_BODY.replace(
        "## Verification\n", "## Verification\n" + prose
    ).replace("- [x]", "- [ ]")
    violations = check_body(unchecked)
    assert len(violations) == 1, violations
    assert "Verification" in violations[0] and "check" in violations[0].lower(), violations
    checked = unchecked.replace("- [ ]", "- [x]", 1)
    assert check_body(checked) == []


def test_missing_pr_body_env_is_config_error():
    """No PR_BODY in the env is a workflow wiring bug: exit 2, distinct from
    both pass (0) and lint-fail (1)."""
    saved = os.environ.pop("PR_BODY", None)
    try:
        assert main() == 2
    finally:
        if saved is not None:
            os.environ["PR_BODY"] = saved


def test_deterministic():
    """Same body twice yields the identical violation list, in document order."""
    a = check_body(GUTTED_BODY)
    b = check_body(GUTTED_BODY)
    assert a == b
    order = [next(i for i, v in enumerate(a) if name in v) for name in REQUIRED]
    assert order == sorted(order), f"violations not in document order: {a}"


def test_required_sections_coupled_to_template():
    """Coupling guard: every name in REQUIRED must appear as an h2 heading in
    the shipped PR template — matched with the checker's own prefix semantics.
    If the template renames a section, this fails instead of the checker
    silently failing every PR in every born repo."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    headings = [
        m.group(1).strip()
        for m in re.finditer(r"^##\s+(.+?)\s*$", stripped, flags=re.MULTILINE)
    ]
    assert headings, "template has no h2 headings at all"
    for name in REQUIRED:
        assert any(heading_matches(h, name) for h in headings), (
            f"REQUIRED section '{name}' has no matching h2 heading in "
            f"{TEMPLATE_PATH.name} — checker and template have drifted"
        )
    assert isinstance(MIN_CONTENT_CHARS, int) and MIN_CONTENT_CHARS > 0


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
