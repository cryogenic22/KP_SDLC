from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, List


def normalize_rel(path: Path, *, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
        return rel.as_posix()
    except Exception:
        return path.as_posix()


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    p = path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, pat) for pat in patterns)


def filter_paths(paths: List[Path], *, root: Path, include: List[str], exclude: List[str]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        rel = normalize_rel(p, root=root)
        if include and not matches_any(rel, include):
            continue
        if exclude and matches_any(rel, exclude):
            continue
        out.append(p)
    return out

