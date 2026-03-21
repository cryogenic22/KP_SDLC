from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from cathedral_keeper.models import Evidence, Finding
from cathedral_keeper.python_graph import build_import_graph, build_module_index, edge_evidence, strongly_connected_components


def check_cycles(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)
    sccs = strongly_connected_components(graph)
    findings: List[Finding] = []
    for comp in sccs[:50]:
        ev = _cycle_evidence(graph, comp)
        findings.append(
            Finding(
                policy_id="CK-PY-CYCLES",
                title=f"Python import cycle ({len(comp)} files)",
                severity=_severity(cfg, default="high"),
                confidence="high",
                why_it_matters="Import cycles increase coupling and make refactors fragile; they also cause runtime import-order bugs.",
                evidence=ev,
                fix_options=["Extract shared types/helpers into a leaf module to break the cycle."],
                verification=["python -m compileall -q " + " ".join({e.file for e in ev})],
                metadata={"cycle": comp},
            )
        )
    return findings


def _cycle_evidence(graph, comp: List[str]) -> List[Evidence]:
    ev: List[Evidence] = []
    for i in range(len(comp)):
        src = comp[i]
        dst = comp[(i + 1) % len(comp)]
        hit = edge_evidence(graph, src=src, dst=dst)
        if hit:
            line, snippet = hit
            ev.append(Evidence(file=src, line=line, snippet=snippet, note=f"imports {dst}"))
    if not ev and comp:
        ev.append(Evidence(file=comp[0], line=1, snippet="cycle detected", note="no edge evidence"))
    return ev[:10]


def _severity(cfg: Dict[str, Any], *, default: str) -> str:
    return str(cfg.get("severity") or default).strip().lower()
