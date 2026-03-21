from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


def resolve_python_roots(
    root: Path,
    config_roots: list,
) -> List[Tuple[str, Path]]:
    """Resolve Python package roots for import graph construction.

    If *config_roots* is non-empty, use the explicit configuration.
    Otherwise fall back to automatic discovery.

    Parameters
    ----------
    root:
        Repository root directory.
    config_roots:
        List of dicts with ``prefix`` and ``path`` keys, taken from
        the ``python_roots`` field in ``.cathedral-keeper.json``.
        Example::

            [
                {"prefix": "src", "path": "myproject/src"},
                {"prefix": "backend", "path": "myproject/backend"}
            ]

    Returns
    -------
    list of (module_prefix, directory) tuples used by
    :func:`python_graph.build_module_index`.
    """
    if config_roots:
        return _roots_from_config(root, config_roots)
    return discover_python_roots(root)


def _roots_from_config(
    root: Path, entries: list
) -> List[Tuple[str, Path]]:
    """Build roots list from explicit config entries."""
    out: List[Tuple[str, Path]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        prefix = str(entry.get("prefix", "")).strip()
        rel_path = str(entry.get("path", "")).strip()
        if not prefix or not rel_path:
            continue
        abs_path = (root / rel_path).resolve()
        if abs_path.is_dir():
            out.append((prefix, abs_path))
    return out


def discover_python_roots(root: Path) -> List[Tuple[str, Path]]:
    """Auto-discover Python package roots in the repository.

    Scans the top two directory levels under *root* for directories
    containing ``__init__.py`` and registers each as a root.
    Also registers the repo root itself if it directly contains
    ``.py`` files.
    """
    roots: List[Tuple[str, Path]] = []

    # Check if root itself has Python files (flat layout)
    if any(root.glob("*.py")):
        roots.append(("", root))

    # Scan top two levels for packages
    for child in _sorted_dirs(root):
        if _is_skip(child):
            continue
        if (child / "__init__.py").exists():
            roots.append((child.name, child))
            continue
        # Second level: look for packages inside common container dirs
        # (e.g. src/, lib/, packages/)
        for grandchild in _sorted_dirs(child):
            if _is_skip(grandchild):
                continue
            if (grandchild / "__init__.py").exists():
                roots.append((grandchild.name, grandchild))

    return roots


def _sorted_dirs(path: Path) -> List[Path]:
    """Return sorted list of immediate subdirectories."""
    try:
        return sorted(d for d in path.iterdir() if d.is_dir())
    except PermissionError:
        return []


_SKIP_NAMES = frozenset({
    "__pycache__", ".git", ".hg", ".svn",
    "node_modules", ".venv", "venv", ".tox",
    "dist", "build", ".eggs", "site-packages",
    ".quality-reports",
})


def _is_skip(path: Path) -> bool:
    """Return True if directory should be skipped during discovery."""
    name = path.name
    return name.startswith(".") and name not in {"."} or name in _SKIP_NAMES
