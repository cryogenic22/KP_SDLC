"""Tests for gen_codeowners: protected-surface.txt -> CODEOWNERS + drift check.

The Structural Floor couples three things so the success-definition surface
cannot be quietly relocated: protected-surface.txt (source of truth) ->
generated CODEOWNERS -> a sync test that fails on drift. These tests cover
the generator and the drift detector.

TDD: written before gen_codeowners.py exists, so the import fails (RED).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gen_codeowners import parse_protected_surface, render_codeowners, check_sync


SAMPLE = """\
# Protected surface — the success-definition surface.
# default-owner: @team-lead

quality-gate/quality_gate.py
cathedral-keeper/cathedral-keeper.config.json  @arch-lead
.github/workflows/
"""

NO_DEFAULT = """\
# no default-owner directive here
quality-gate/quality_gate.py
"""


def test_parse_extracts_default_owner():
    default_owner, _ = parse_protected_surface(SAMPLE)
    assert default_owner == "@team-lead"


def test_parse_extracts_entries_ignoring_comments_and_blanks():
    _, entries = parse_protected_surface(SAMPLE)
    paths = [p for p, _ in entries]
    assert paths == [
        "quality-gate/quality_gate.py",
        "cathedral-keeper/cathedral-keeper.config.json",
        ".github/workflows/",
    ]


def test_parse_keeps_explicit_owners_separate_from_default():
    _, entries = parse_protected_surface(SAMPLE)
    by_path = dict(entries)
    assert by_path["quality-gate/quality_gate.py"] == []          # uses default later
    assert by_path["cathedral-keeper/cathedral-keeper.config.json"] == ["@arch-lead"]


def test_render_has_generated_do_not_edit_header():
    out = render_codeowners(*parse_protected_surface(SAMPLE))
    assert "DO NOT EDIT" in out
    assert "protected-surface.txt" in out


def test_render_one_line_per_entry_with_resolved_owner():
    out = render_codeowners(*parse_protected_surface(SAMPLE))
    assert "quality-gate/quality_gate.py @team-lead" in out
    assert "cathedral-keeper/cathedral-keeper.config.json @arch-lead" in out
    assert ".github/workflows/ @team-lead" in out


def test_render_is_deterministic_and_order_preserving():
    a = render_codeowners(*parse_protected_surface(SAMPLE))
    b = render_codeowners(*parse_protected_surface(SAMPLE))
    assert a == b
    # order of paths preserved from the surface file
    assert a.index("quality_gate.py") < a.index("workflows/")


def test_entry_without_owner_and_no_default_fails_loud():
    """An unenforceable protection (no owner anywhere) must error, not emit a vacuous line."""
    try:
        render_codeowners(*parse_protected_surface(NO_DEFAULT))
    except ValueError:
        return
    raise AssertionError("expected ValueError when an entry has no owner and no default")


def test_check_sync_true_when_codeowners_matches():
    generated = render_codeowners(*parse_protected_surface(SAMPLE))
    in_sync, _ = check_sync(SAMPLE, generated)
    assert in_sync is True


def test_check_sync_detects_drift():
    generated = render_codeowners(*parse_protected_surface(SAMPLE))
    tampered = generated.replace("@arch-lead", "@someone-else")
    in_sync, msg = check_sync(SAMPLE, tampered)
    assert in_sync is False
    assert msg  # a non-empty explanation


def test_check_sync_ignores_trailing_whitespace_noise():
    generated = render_codeowners(*parse_protected_surface(SAMPLE))
    noisy = generated.rstrip() + "\n\n\n"  # extra trailing blank lines only
    in_sync, _ = check_sync(SAMPLE, noisy)
    assert in_sync is True


# ── Owner-validity guards (no vacuous green) ──────────────────────────

PLACEHOLDER = """\
# default-owner: {{OWNER}}
quality-gate/quality_gate.py
"""

BAD_OWNER = """\
quality-gate/quality_gate.py notanowner
"""

EMPTY = """\
# only comments and blanks
# default-owner: @team-lead

"""


def test_unsubstituted_placeholder_owner_fails_loud():
    """A {{OWNER}} that was never substituted is an unenforceable CODEOWNERS — must error."""
    try:
        render_codeowners(*parse_protected_surface(PLACEHOLDER))
    except ValueError as e:
        assert "placeholder" in str(e).lower() or "{{" in str(e)
        return
    raise AssertionError("expected ValueError for unsubstituted {{OWNER}} placeholder")


def test_invalid_owner_format_fails_loud():
    """An owner GitHub would ignore (not @handle/@org-team/email) must error, not pass green."""
    try:
        render_codeowners(*parse_protected_surface(BAD_OWNER))
    except ValueError:
        return
    raise AssertionError("expected ValueError for invalid owner format 'notanowner'")


def test_empty_surface_fails_loud():
    """A surface that protects nothing must not render a green header-only CODEOWNERS."""
    try:
        render_codeowners(*parse_protected_surface(EMPTY))
    except ValueError:
        return
    raise AssertionError("expected ValueError for an empty protected surface")


def test_valid_owner_forms_accepted():
    for owner in ("@user", "@org/team", "dev@example.com"):
        surface = f"# default-owner: {owner}\nquality-gate/quality_gate.py\n"
        out = render_codeowners(*parse_protected_surface(surface))
        assert f"quality-gate/quality_gate.py {owner}" in out


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
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
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
