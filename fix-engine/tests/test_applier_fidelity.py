"""E0.8 — byte-fidelity write path: preserve EOL style and trailing newline.

Guarantee under test: read->fix->write must preserve the file's original
line-ending style (CRLF vs LF) and its trailing-newline presence.

Anti-case: a pure-LF file stays pure LF (guards against blanket CRLF
forcing as a "fix" for the CRLF bug).

Run standalone:
    python fix-engine/tests/test_applier_fidelity.py
"""

from __future__ import annotations

import os
import sys
import tempfile

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fe.applier import apply_patches
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


# ── E0.8 guarantee tests (RED before implementation) ─────────────────

def test_crlf_preserved():
    """A CRLF file must stay CRLF on every line after patching."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "crlf.py")
        _write_bytes(fpath, b"a = 1\r\nb = 2\r\n")
        p = _patch(fpath, 1, "a = 1", "a = 9")

        applied, skipped = apply_patches(fpath, [p], dry_run=False, backup=False)

        assert len(applied) == 1, f"patch skipped: {skipped}"
        raw = _read_bytes(fpath)
        assert raw == b"a = 9\r\nb = 2\r\n", f"CRLF not preserved: {raw!r}"


def test_no_trailing_newline_preserved():
    """A file without a trailing newline must not gain one."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "tail.py")
        _write_bytes(fpath, b"a = 1\nb = 2")  # no trailing newline
        p = _patch(fpath, 2, "b = 2", "b = 9")

        applied, skipped = apply_patches(fpath, [p], dry_run=False, backup=False)

        assert len(applied) == 1, f"patch skipped: {skipped}"
        raw = _read_bytes(fpath)
        assert raw == b"a = 1\nb = 9", (
            f"trailing-newline state not preserved: {raw!r}"
        )


def test_crlf_without_trailing_newline():
    """CRLF style and missing trailing newline preserved together."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "combo.py")
        _write_bytes(fpath, b"a = 1\r\nb = 2")  # CRLF, no trailing newline
        p = _patch(fpath, 1, "a = 1", "a = 9")

        applied, skipped = apply_patches(fpath, [p], dry_run=False, backup=False)

        assert len(applied) == 1, f"patch skipped: {skipped}"
        raw = _read_bytes(fpath)
        assert raw == b"a = 9\r\nb = 2", f"fidelity lost: {raw!r}"


# ── Anti-case (must be green before AND after) ───────────────────────

def test_lf_file_stays_lf():
    """Anti-case: a pure-LF file must stay pure LF with trailing newline."""
    with tempfile.TemporaryDirectory() as tmp:
        fpath = os.path.join(tmp, "lf.py")
        _write_bytes(fpath, b"a = 1\nb = 2\n")
        p = _patch(fpath, 1, "a = 1", "a = 9")

        applied, skipped = apply_patches(fpath, [p], dry_run=False, backup=False)

        assert len(applied) == 1, f"patch skipped: {skipped}"
        raw = _read_bytes(fpath)
        assert raw == b"a = 9\nb = 2\n", f"LF file altered: {raw!r}"


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
