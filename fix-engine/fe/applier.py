"""Patch application module.

Provides helpers to generate unified diffs, apply FixPatches to files,
and drive a full FixResult through the pipeline.
"""

from __future__ import annotations

import difflib
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fe.types import FixPatch, FixResult


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------

def generate_diff(
    file_path: str,
    original_lines: List[str],
    fixed_lines: List[str],
) -> str:
    """Return a unified-diff string comparing *original_lines* to *fixed_lines*."""
    return "".join(
        difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )


# ---------------------------------------------------------------------------
# Patch application
# ---------------------------------------------------------------------------

def _read_lines(path: Path) -> List[str]:
    """Read file and return list of lines (with newlines stripped)."""
    with open(path, "r", encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh.readlines()]


def _write_lines(path: Path, lines: List[str]) -> None:
    """Write lines back to file, adding newlines."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        for line in lines:
            fh.write(line + "\n")


def apply_patches(
    file_path: str,
    patches: List[FixPatch],
    dry_run: bool = False,
    backup: bool = True,
) -> Tuple[List[FixPatch], List[Dict[str, Any]]]:
    """Apply *patches* to *file_path*.

    Patches are sorted by line number **descending** so that earlier line
    numbers are not shifted by later replacements.

    Returns ``(applied, skipped)`` where *applied* is the list of
    successfully applied patches and *skipped* is a list of dicts
    describing each skipped patch and the reason.
    """
    path = Path(file_path)
    lines = _read_lines(path)

    applied: List[FixPatch] = []
    skipped: List[Dict[str, Any]] = []

    # Sort descending by line number so bottom edits don't shift top ones.
    sorted_patches = sorted(patches, key=lambda p: p.line, reverse=True)

    for patch in sorted_patches:
        idx = patch.line - 1  # 0-based index
        if idx < 0 or idx >= len(lines):
            skipped.append({
                "patch": patch,
                "reason": f"Line {patch.line} out of range (file has {len(lines)} lines)",
            })
            continue

        # Validate: the original text must match the actual line.
        actual = lines[idx]
        if actual.rstrip() != patch.original.rstrip():
            skipped.append({
                "patch": patch,
                "reason": (
                    f"Content mismatch at line {patch.line}: "
                    f"expected {patch.original!r}, found {actual!r}"
                ),
            })
            continue

        # Replace the line(s).
        replacement_lines = patch.replacement.split("\n") if patch.replacement else [""]
        original_line_count = len(patch.original.split("\n")) if patch.original else 1
        lines[idx: idx + original_line_count] = replacement_lines
        applied.append(patch)

    if not dry_run and applied:
        if backup:
            shutil.copy2(str(path), str(path) + ".bak")
        _write_lines(path, lines)

    return applied, skipped


def apply_fix_result(
    result: FixResult,
    dry_run: bool = False,
    backup: bool = True,
) -> FixResult:
    """Apply all patches in *result*, grouped by file.

    Updates *result.applied* and *result.skipped* in place and returns it.
    """
    # Group patches by file
    by_file: Dict[str, List[FixPatch]] = {}
    for patch in result.patches:
        by_file.setdefault(patch.file_path, []).append(patch)

    all_applied: List[FixPatch] = []
    all_skipped: List[Dict[str, Any]] = []

    for fpath, patches in by_file.items():
        applied, skipped = apply_patches(
            fpath, patches, dry_run=dry_run, backup=backup
        )
        all_applied.extend(applied)
        all_skipped.extend(skipped)

    result.applied = all_applied
    result.skipped = all_skipped
    result.stats = result.summary()
    return result
