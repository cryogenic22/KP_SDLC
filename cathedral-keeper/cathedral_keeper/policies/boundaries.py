from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from cathedral_keeper.models import Evidence, Finding, clamp_snippet
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_graph import build_import_graph, build_module_index


def check_boundaries(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    rules = list((cfg.get("config") or {}).get("rules") or [])
    if not rules:
        return []

    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    findings: List[Finding] = []
    for edge in graph.edges:
        for rule in rules:
            hit = _violates(edge.src_file, edge.module, rule)
            if not hit:
                continue
            findings.append(
                Finding(
                    policy_id=str(rule.get("id") or "CK-PY-BOUNDARIES"),
                    title=str(rule.get("title") or "Architecture boundary violation"),
                    severity=str(rule.get("severity") or "high").lower(),
                    confidence="high",
                    why_it_matters=str(rule.get("why") or "Boundary violations create tight coupling across subsystems."),
                    evidence=[
                        Evidence(
                            file=edge.src_file,
                            line=int(edge.line),
                            snippet=clamp_snippet(f"import {edge.module}"),
                            note=f"imports forbidden module prefix: {hit}",
                        )
                    ],
                    fix_options=[str(rule.get("fix") or "Move the dependency behind a stable interface or relocate shared code.")],
                    verification=["python -m compileall -q " + edge.src_file],
                    metadata={"dst_file": edge.dst_file, "module": edge.module},
                )
            )
    return findings


def _violates(src_file: str, imported_module: str, rule: Dict[str, Any]) -> str:
    src_ok = matches_any(src_file, [str(rule.get("from") or "")])
    if not src_ok:
        return ""

    allowed = list(rule.get("allowed_from", []) or [])
    if allowed and matches_any(src_file, allowed):
        return ""

    prefixes = [str(x).strip() for x in (rule.get("to_module_prefixes") or []) if str(x).strip()]
    for pfx in prefixes:
        if imported_module == pfx or imported_module.startswith(pfx + "."):
            return pfx
    return ""

