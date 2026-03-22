"""Tests for fe.applier — patch application logic."""

import sys
import os
import tempfile
import shutil
import unittest
from pathlib import Path

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fe.types import FixPatch, FixResult
from fe.applier import generate_diff, apply_patches, apply_fix_result


def _make_patch(
    rule_id="R-001",
    file_path="tmp.py",
    line=1,
    original="old",
    replacement="new",
    explanation="fix it",
    confidence=0.95,
    category="safe",
):
    return FixPatch(
        rule_id=rule_id,
        file_path=file_path,
        line=line,
        original=original,
        replacement=replacement,
        explanation=explanation,
        confidence=confidence,
        category=category,
    )


class TestGenerateDiff(unittest.TestCase):
    """generate_diff produces unified diff output."""

    def test_generate_diff_format(self):
        orig = ["alpha", "beta", "gamma"]
        fixed = ["alpha", "BETA", "gamma"]
        diff = generate_diff("hello.py", orig, fixed)
        self.assertIn("a/hello.py", diff)
        self.assertIn("b/hello.py", diff)
        self.assertIn("-beta", diff)
        self.assertIn("+BETA", diff)


class TestApplyPatches(unittest.TestCase):
    """apply_patches correctness."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, lines: list[str]) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        return path

    def _read(self, path: str) -> list[str]:
        with open(path, "r", encoding="utf-8") as fh:
            return [l.rstrip("\n") for l in fh.readlines()]

    # ------------------------------------------------------------------ #
    # 1. Patches are applied bottom-to-top (descending line order)
    # ------------------------------------------------------------------ #
    def test_apply_patches_descending_order(self):
        fpath = self._write("desc.py", ["line1", "line2", "line3"])
        p1 = _make_patch(file_path=fpath, line=1, original="line1", replacement="LINE1")
        p3 = _make_patch(file_path=fpath, line=3, original="line3", replacement="LINE3")

        applied, skipped = apply_patches(fpath, [p1, p3], dry_run=False, backup=False)
        content = self._read(fpath)

        self.assertEqual(len(applied), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(content, ["LINE1", "line2", "LINE3"])

    # ------------------------------------------------------------------ #
    # 2. Mismatched original text → skip
    # ------------------------------------------------------------------ #
    def test_skip_mismatched_patch(self):
        fpath = self._write("mis.py", ["hello world"])
        patch = _make_patch(file_path=fpath, line=1, original="goodbye", replacement="hi")

        applied, skipped = apply_patches(fpath, [patch], dry_run=False, backup=False)
        self.assertEqual(len(applied), 0)
        self.assertEqual(len(skipped), 1)
        self.assertIn("mismatch", skipped[0]["reason"].lower())

    # ------------------------------------------------------------------ #
    # 3. dry_run does NOT modify the file
    # ------------------------------------------------------------------ #
    def test_dry_run_no_file_modification(self):
        fpath = self._write("dry.py", ["old_line"])
        patch = _make_patch(file_path=fpath, line=1, original="old_line", replacement="new_line")

        applied, _ = apply_patches(fpath, [patch], dry_run=True, backup=False)
        self.assertEqual(len(applied), 1)
        # File must remain unchanged
        self.assertEqual(self._read(fpath), ["old_line"])

    # ------------------------------------------------------------------ #
    # 4. Backup file is created
    # ------------------------------------------------------------------ #
    def test_backup_file_created(self):
        fpath = self._write("bak.py", ["original"])
        patch = _make_patch(file_path=fpath, line=1, original="original", replacement="fixed")

        apply_patches(fpath, [patch], dry_run=False, backup=True)
        self.assertTrue(os.path.exists(fpath + ".bak"))
        # Backup should contain the original content
        self.assertEqual(self._read(fpath + ".bak"), ["original"])

    # ------------------------------------------------------------------ #
    # 5. Multiple patches on the same file
    # ------------------------------------------------------------------ #
    def test_multiple_patches_same_file(self):
        fpath = self._write("multi.py", ["aaa", "bbb", "ccc", "ddd"])
        patches = [
            _make_patch(file_path=fpath, line=2, original="bbb", replacement="BBB"),
            _make_patch(file_path=fpath, line=4, original="ddd", replacement="DDD"),
        ]

        applied, skipped = apply_patches(fpath, patches, dry_run=False, backup=False)
        self.assertEqual(len(applied), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(self._read(fpath), ["aaa", "BBB", "ccc", "DDD"])

    # ------------------------------------------------------------------ #
    # 6. Empty patches list → no changes
    # ------------------------------------------------------------------ #
    def test_empty_patches_list(self):
        fpath = self._write("empty.py", ["stay"])
        applied, skipped = apply_patches(fpath, [], dry_run=False, backup=False)
        self.assertEqual(applied, [])
        self.assertEqual(skipped, [])
        self.assertEqual(self._read(fpath), ["stay"])

    # ------------------------------------------------------------------ #
    # 7. Partial failure — good patches still applied
    # ------------------------------------------------------------------ #
    def test_partial_failure_applies_others(self):
        fpath = self._write("partial.py", ["good", "stays", "good2"])
        good_patch = _make_patch(file_path=fpath, line=1, original="good", replacement="GOOD")
        bad_patch = _make_patch(file_path=fpath, line=2, original="WRONG", replacement="X")
        good2_patch = _make_patch(file_path=fpath, line=3, original="good2", replacement="GOOD2")

        applied, skipped = apply_patches(
            fpath, [good_patch, bad_patch, good2_patch], dry_run=False, backup=False
        )
        self.assertEqual(len(applied), 2)
        self.assertEqual(len(skipped), 1)
        content = self._read(fpath)
        self.assertEqual(content, ["GOOD", "stays", "GOOD2"])

    # ------------------------------------------------------------------ #
    # 8. apply_fix_result drives per-file grouping
    # ------------------------------------------------------------------ #
    def test_apply_fix_result_groups_by_file(self):
        f1 = self._write("a.py", ["x"])
        f2 = self._write("b.py", ["y"])
        result = FixResult(
            patches=[
                _make_patch(file_path=f1, line=1, original="x", replacement="X"),
                _make_patch(file_path=f2, line=1, original="y", replacement="Y"),
            ]
        )

        result = apply_fix_result(result, dry_run=False, backup=False)
        self.assertEqual(len(result.applied), 2)
        self.assertEqual(len(result.skipped), 0)
        self.assertEqual(self._read(f1), ["X"])
        self.assertEqual(self._read(f2), ["Y"])


if __name__ == "__main__":
    unittest.main()
