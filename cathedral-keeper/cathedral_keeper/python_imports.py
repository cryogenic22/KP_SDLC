from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass(frozen=True, slots=True)
class PyImport:
    module: str
    lineno: int
    kind: str  # import|from


def parse_imports(source: str) -> List[PyImport]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    out: List[PyImport] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = str(alias.name or "").strip()
                if name:
                    out.append(PyImport(module=name, lineno=int(node.lineno or 1), kind="import"))
        elif isinstance(node, ast.ImportFrom):
            base = str(node.module or "").strip()
            if not base:
                continue
            out.append(PyImport(module=base, lineno=int(node.lineno or 1), kind="from"))
    return out


def read_text_best_effort(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def iter_python_files(root: Path) -> Iterable[Path]:
    yield from root.rglob("*.py")


def resolve_internal_import_target(module: str, *, module_index: dict[str, str]) -> Optional[str]:
    """
    Resolve an import module string to an internal file path (best-effort).

    Resolution tries full module then progressively strips suffixes:
      a.b.c -> a.b.c, a.b, a
    """
    m = str(module or "").strip()
    if not m:
        return None
    if m in module_index:
        return module_index[m]
    parts = m.split(".")
    for i in range(len(parts) - 1, 0, -1):
        key = ".".join(parts[:i])
        if key in module_index:
            return module_index[key]
    return None

