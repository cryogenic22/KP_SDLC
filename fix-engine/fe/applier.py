"""Patch application module.

Provides helpers to generate unified diffs, apply FixPatches to files,
and drive a full FixResult through the pipeline.
"""

from __future__ import annotations

import ast
import difflib
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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

def _read_text(path: Path) -> str:
    """Read the raw file text without any newline translation."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _split_content(content: str) -> Tuple[List[str], str, bool]:
    """Split *content* into ``(lines, eol, trailing_newline)``.

    ``eol`` is the file's dominant line ending (``\\r\\n`` when any CRLF
    is present, else ``\\n``); ``trailing_newline`` records whether the
    file ended with a newline, so the write path can preserve both.
    """
    eol = "\r\n" if "\r\n" in content else "\n"
    trailing = content.endswith("\n")
    if not content:
        return [], eol, False
    lines = content.replace("\r\n", "\n").split("\n")
    if trailing and lines and lines[-1] == "":
        lines.pop()
    return lines, eol, trailing


def _read_lines(path: Path) -> Tuple[List[str], str, bool]:
    """Read file and return ``(lines, eol, trailing_newline)``."""
    return _split_content(_read_text(path))


def _write_lines(
    path: Path,
    lines: List[str],
    eol: str = "\n",
    trailing: bool = True,
) -> None:
    """Write lines back, preserving EOL style and trailing-newline state."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(eol.join(lines) + (eol if trailing else ""))


# ---------------------------------------------------------------------------
# Post-apply syntax validation
# ---------------------------------------------------------------------------

def _validate_python(text: str) -> Optional[str]:
    """Return an error message when *text* is not valid Python, else None."""
    try:
        ast.parse(text)
    except SyntaxError as exc:
        return str(exc)
    return None


# Suffix-keyed validators; suffixes not listed here are never blocked.
_VALIDATORS: Dict[str, Callable[[str], Optional[str]]] = {
    ".py": _validate_python,
    ".pyi": _validate_python,
}


def _validate(path: Path, text: str) -> Optional[str]:
    """Return an error message when *text* is invalid for *path*'s type."""
    validator = _VALIDATORS.get(path.suffix.lower())
    if validator is None:
        return None
    return validator(text)


def _write_validated(
    path: Path,
    lines: List[str],
    eol: str,
    trailing: bool,
    original_text: str,
    backup: bool,
) -> Optional[str]:
    """Validate *lines* for *path*, then write them; return a skip reason.

    On a syntax-gate failure the file is left untouched and the reason is
    returned. A .bak is created first when *backup* is true; on a mid-write
    failure the original file is restored (from the .bak, or from memory
    when backup was disabled) and the exception re-raised.
    """
    error = _validate(path, "\n".join(lines))
    if error is not None:
        return f"post-apply syntax check failed: {error}"

    bak_path = str(path) + ".bak" if backup else None
    if bak_path is not None:
        shutil.copy2(str(path), bak_path)
    try:
        _write_lines(path, lines, eol, trailing)
    except BaseException:
        if bak_path is not None:
            shutil.copy2(bak_path, str(path))
        else:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(original_text)
        raise
    return None


def _apply_one(lines: List[str], patch: FixPatch) -> Optional[str]:
    """Apply *patch* to *lines* in place; return a skip reason on failure."""
    idx = patch.line - 1  # 0-based index
    if idx < 0 or idx >= len(lines):
        return f"Line {patch.line} out of range (file has {len(lines)} lines)"

    # Validate: the original text must match the actual line.
    actual = lines[idx]
    if actual.rstrip() != patch.original.rstrip():
        return (
            f"Content mismatch at line {patch.line}: "
            f"expected {patch.original!r}, found {actual!r}"
        )

    # Replace the line(s).
    replacement_lines = patch.replacement.split("\n") if patch.replacement else [""]
    original_line_count = len(patch.original.split("\n")) if patch.original else 1
    lines[idx: idx + original_line_count] = replacement_lines
    return None


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
    original_text = _read_text(path)
    lines, eol, trailing = _split_content(original_text)

    applied: List[FixPatch] = []
    skipped: List[Dict[str, Any]] = []

    # Sort descending by line number so bottom edits don't shift top ones.
    sorted_patches = sorted(patches, key=lambda p: p.line, reverse=True)

    for patch in sorted_patches:
        reason = _apply_one(lines, patch)
        if reason is not None:
            skipped.append({"patch": patch, "reason": reason})
        else:
            applied.append(patch)

    if not dry_run and applied:
        # Post-apply syntax gate + restore-on-failure: on a gate failure
        # the file is untouched and every "applied" patch is skipped.
        reason = _write_validated(path, lines, eol, trailing, original_text, backup)
        if reason is not None:
            skipped.extend({"patch": p, "reason": reason} for p in applied)
            return [], skipped

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
