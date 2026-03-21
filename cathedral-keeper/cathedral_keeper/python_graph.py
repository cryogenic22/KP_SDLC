from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from cathedral_keeper.models import clamp_snippet, normalize_path
from cathedral_keeper.python_imports import parse_imports, read_text_best_effort, resolve_internal_import_target


@dataclass(frozen=True, slots=True)
class ImportEdge:
    src_file: str
    dst_file: str
    module: str
    line: int


@dataclass(frozen=True, slots=True)
class PyGraph:
    module_index: Dict[str, str]  # module -> rel file path
    edges: List[ImportEdge]


def build_module_index(*, root: Path, python_roots: List[Tuple[str, Path]]) -> Dict[str, str]:
    """
    Build module->file index for internal resolution.

    `python_roots` is a list of (module_prefix, directory) pairs.
    Example:
      ("src", <repo>/medcontent-ai-platform/agents/src)
    """
    out: Dict[str, str] = {}
    root_resolved = root.resolve()
    for prefix, base in python_roots:
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = normalize_path(str(path.resolve().relative_to(root_resolved)))
            mod = _module_name_for_file(prefix=prefix, base=base, path=path)
            if mod:
                out[mod] = rel
    return out


def _module_name_for_file(*, prefix: str, base: Path, path: Path) -> str:
    rel = path.resolve().relative_to(base.resolve()).as_posix()
    if rel.endswith("/__init__.py"):
        rel = rel[: -len("/__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[: -len(".py")]
    rel = rel.strip("/")
    if not rel:
        return prefix
    return f"{prefix}.{rel.replace('/', '.')}"


def build_import_graph(*, root: Path, files: List[Path], module_index: Dict[str, str]) -> PyGraph:
    root_resolved = root.resolve()
    edges: List[ImportEdge] = []
    for path in files:
        text = read_text_best_effort(path)
        rel_src = normalize_path(str(path.resolve().relative_to(root_resolved)))
        for imp in parse_imports(text):
            dst_rel = resolve_internal_import_target(imp.module, module_index=module_index)
            if not dst_rel:
                continue
            edges.append(ImportEdge(src_file=rel_src, dst_file=dst_rel, module=imp.module, line=imp.lineno))
    return PyGraph(module_index=module_index, edges=edges)


def strongly_connected_components(graph: PyGraph) -> List[List[str]]:
    nodes: Set[str] = set()
    adj: Dict[str, List[str]] = {}
    for e in graph.edges:
        nodes.add(e.src_file)
        nodes.add(e.dst_file)
        adj.setdefault(e.src_file, []).append(e.dst_file)

    index = 0
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlink: Dict[str, int] = {}
    out: List[List[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])

        if lowlink[v] == indices[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in sorted(nodes):
        if v not in indices:
            strongconnect(v)
    return out


def edge_evidence(graph: PyGraph, *, src: str, dst: str) -> Optional[Tuple[int, str]]:
    for e in graph.edges:
        if e.src_file == src and e.dst_file == dst:
            return e.line, clamp_snippet(f"import {e.module}")
    return None

