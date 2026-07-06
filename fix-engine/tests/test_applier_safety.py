"""E0.7 — applier safety: post-apply syntax gate + restore-on-write-failure.

Guarantee under test: a fixer write can never leave a Python file
syntactically broken, and a mid-write failure restores the original
content (from the .bak when one exists, from memory otherwise).

Anti-cases: valid Python still applies; non-Python files are never
blocked by the syntax gate.

Run standalone:
    python fix-engine/tests/test_applier_safety.py
"""

from __future__ import annotations

import os
import sys
import tempfile

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fe.applier as applier
from fe.types import FixPatch


# ── Helpers ───────────────────────────────────────────────────────────

def _patch(file_path: str, line: int, original: str, replacement: str) -> FixPatch:
    return FixPatch(
        rule_id="R-TEST",
        file_path=file_path,
        line=line,
        original=original,
        replacement=replacement,
        explanation="test patch",
        confidence=0.99,
        category="safe",
    )


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


class _ExplodingWrite:
    """Replacement for _write_lines that corrupts the file, then raises.

    Simulates a mid-write crash (disk full / process kill): the target
    file is left truncated before the exception surfaces.
    """

    def __call__(self, path, lines, *args, **kwargs):
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("a =")  # truncated garbage
        raise IOError("simulated mid-write failure")


# ── E0.7 guarantee tests (RED before implementation) ─────────────────

def test_syntax_error_result_rolls_back():
    """A patch producing invalid Python must leave the file intact."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "victim.py")
        original = b"x = 1\ny = 2\n"
        _write_bytes(fpath, original)
        bad = _patch(fpath, 1, "x = 1", "def broken(:")

        applied, skipped = applier.apply_patches(
            fpath, [bad], dry_run=False, backup=True
        )

        content = _read_bytes(fpath)
        assert content == original, f"file was corrupted: {content!r}"
        assert applied == [], f"broken patch reported as applied: {applied}"
        assert len(skipped) == 1, f"expected 1 skipped patch, got: {skipped}"
        assert "syntax" in skipped[0]["reason"].lower(), (
            f"skip reason must mention syntax: {skipped[0]['reason']!r}"
        )
        # .bak may be absent (gate fired before backup) or must hold the original
        bak = fpath + ".bak"
        if os.path.exists(bak):
            assert _read_bytes(bak) == original


def test_write_failure_restores_from_bak():
    """A mid-write crash must restore the original file from the .bak."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "victim.py")
        original = b"a = 1\n"
        _write_bytes(fpath, original)
        good = _patch(fpath, 1, "a = 1", "a = 2")

        real_write = applier._write_lines
        applier._write_lines = _ExplodingWrite()
        try:
            raised = False
            try:
                applier.apply_patches(fpath, [good], dry_run=False, backup=True)
            except IOError:
                raised = True
            assert raised, "write failure was swallowed silently"
        finally:
            applier._write_lines = real_write

        content = _read_bytes(fpath)
        assert content == original, (
            f"file not restored after write failure: {content!r}"
        )


def test_write_failure_restores_without_backup():
    """With backup=False the original content must be restored from memory."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "victim.py")
        original = b"b = 1\n"
        _write_bytes(fpath, original)
        good = _patch(fpath, 1, "b = 1", "b = 2")

        real_write = applier._write_lines
        applier._write_lines = _ExplodingWrite()
        try:
            raised = False
            try:
                applier.apply_patches(fpath, [good], dry_run=False, backup=False)
            except IOError:
                raised = True
            assert raised, "write failure was swallowed silently"
        finally:
            applier._write_lines = real_write

        content = _read_bytes(fpath)
        assert content == original, (
            f"file not restored (backup=False path): {content!r}"
        )


# ── Regression: UTF-8-BOM files (adversarial review blocker) ─────────

def test_bom_file_valid_patch_still_applies():
    """A UTF-8-BOM'd valid Python file must not be blocked by the gate.

    Regression: ast.parse() on a decoded str rejects a leading U+FEFF,
    so the syntax gate falsely reported 'invalid non-printable character
    U+FEFF' for every BOM'd .py file even when the patched result was
    valid Python (CPython itself runs BOM'd source via utf-8-sig).
    """
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "bom.py")
        _write_bytes(fpath, b"\xef\xbb\xbfx = 1\ny = 2\n")
        p = _patch(fpath, 2, "y = 2", "y = 9")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=True
        )

        assert len(applied) == 1 and not skipped, (
            f"BOM'd valid Python was blocked: {skipped}"
        )
        content = _read_bytes(fpath)
        assert content == b"\xef\xbb\xbfx = 1\ny = 9\n", (
            f"fix not applied or BOM lost: {content!r}"
        )


def test_bom_file_broken_patch_still_blocked():
    """Guard: the gate must still fire on BOM'd files with broken output."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "bom_bad.py")
        original = b"\xef\xbb\xbfx = 1\ny = 2\n"
        _write_bytes(fpath, original)
        bad = _patch(fpath, 2, "y = 2", "def broken(:")

        applied, skipped = applier.apply_patches(
            fpath, [bad], dry_run=False, backup=True
        )

        assert applied == [], f"broken patch applied on BOM'd file: {applied}"
        assert len(skipped) == 1 and "syntax" in skipped[0]["reason"].lower()
        assert _read_bytes(fpath) == original, "BOM'd file was corrupted"


# ── Regression: CRLF inside patch text (adversarial review major) ────

def test_crlf_replacement_never_smuggles_cr_into_lf_file():
    """A patch replacement carrying \\r\\n must not produce mixed EOL.

    Regression: _apply_one split the replacement on '\\n' only, leaving
    '\\r' inside line bodies — a pure-LF file gained CRLF lines (the
    exact E0.8 bug class the fidelity layer exists to kill).
    """
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "lf.py")
        _write_bytes(fpath, b"a = 1\nb = 2\n")
        p = _patch(fpath, 1, "a = 1", "a = 9\r\nz = 0")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=False
        )

        assert len(applied) == 1 and not skipped, f"patch blocked: {skipped}"
        content = _read_bytes(fpath)
        assert b"\r" not in content, f"CR smuggled into LF file: {content!r}"
        assert content == b"a = 9\nz = 0\nb = 2\n", content


def test_crlf_replacement_no_double_cr_on_crlf_file():
    """On a CRLF file, a CRLF-bearing replacement must not yield \\r\\r\\n."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "crlf.py")
        _write_bytes(fpath, b"a = 1\r\nb = 2\r\n")
        p = _patch(fpath, 1, "a = 1", "a = 9\r\nz = 0")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=False
        )

        assert len(applied) == 1 and not skipped, f"patch blocked: {skipped}"
        content = _read_bytes(fpath)
        assert b"\r\r\n" not in content, f"double-CR phantom line: {content!r}"
        assert content == b"a = 9\r\nz = 0\r\nb = 2\r\n", content


# ── Regression: trailing-\n patch text swallowed the next line ───────

def test_trailing_newline_patch_replaces_exactly_one_line():
    """A fixer-style patch ('except:\\n' -> 'except Exception:\\n') must
    replace exactly one line, never swallow the line after it.

    Regression (pre-existing, exposed by the E0.7 gate): the trailing
    '\\n' was counted as a second original line, so the replacement
    consumed the following line ('    pass'), corrupting the file —
    silently written before the syntax gate existed, blocked after.
    """
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "one_line.py")
        _write_bytes(fpath, b"try:\n    x = 1\nexcept:\n    pass\n")
        p = _patch(fpath, 3, "except:\n", "except Exception:\n")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=False
        )

        assert len(applied) == 1 and not skipped, f"patch blocked: {skipped}"
        assert _read_bytes(fpath) == (
            b"try:\n    x = 1\nexcept Exception:\n    pass\n"
        ), "the line after the patch was swallowed or altered"


# ── Anti-cases (must be green before AND after) ──────────────────────

def test_valid_python_patch_still_applies():
    """Anti-case: the syntax gate must not block valid results."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "fine.py")
        _write_bytes(fpath, b"value = 1\n")
        p = _patch(fpath, 1, "value = 1", "value = 2")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=False
        )

        assert len(applied) == 1 and not skipped, f"valid patch blocked: {skipped}"
        assert _read_bytes(fpath) == b"value = 2\n"


def test_non_python_file_not_syntax_gated():
    """Anti-case: non-Python files must never be blocked by the ast gate."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "notes.txt")
        _write_bytes(fpath, b"hello\n")
        # replacement is deliberately invalid Python
        p = _patch(fpath, 1, "hello", "def broken(:")

        applied, skipped = applier.apply_patches(
            fpath, [p], dry_run=False, backup=False
        )

        assert len(applied) == 1 and not skipped, (
            f"non-Python file was syntax-gated: {skipped}"
        )
        assert _read_bytes(fpath) == b"def broken(:\n"


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
