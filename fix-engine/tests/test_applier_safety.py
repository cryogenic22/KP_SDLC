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
