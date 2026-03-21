"""CK-ARCH-LAYER-DIRECTION — Dependency Direction Enforcement.

Defines architectural layers and ensures imports only flow downward.
Layers are listed top-to-bottom in config.  Each layer may import from
layers below it but not above.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path, clamp_snippet
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_graph import PyGraph, build_import_graph, build_module_index


def check_layer_direction(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    layers_cfg = list((cfg.get("config") or cfg).get("layers") or [])
    if not layers_cfg:
        return []

    direction = str((cfg.get("config") or cfg).get("direction", "top-down"))
    allowed_cross = list((cfg.get("config") or cfg).get("allowed_cross_layer") or [])

    # Build layer definitions: list of (name, patterns, rank)
    # rank 0 = topmost layer, rank N = bottommost
    layers: List[Tuple[str, List[str], int]] = []
    for i, entry in enumerate(layers_cfg):
        name = str(entry.get("name", f"layer_{i}"))
        patterns = list(entry.get("patterns") or [])
        layers.append((name, patterns, i))

    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    findings: List[Finding] = []
    for edge in graph.edges:
        src_layer = _classify(edge.src_file, layers)
        dst_layer = _classify(edge.dst_file, layers)
        if src_layer is None or dst_layer is None:
            continue  # files not in any layer — skip
        src_name, src_rank = src_layer
        dst_name, dst_rank = dst_layer
        if src_name == dst_name:
            continue  # same layer — always allowed

        # In top-down mode: source rank must be <= destination rank (higher
        # layers can import lower ones).  A violation is when src is below
        # dst (src_rank > dst_rank means src is a lower layer importing
        # upward) — wait, re-read:
        # rank 0 = topmost.  Layer 0 (routes) may import Layer 1 (services),
        # Layer 1 may import Layer 2, etc.  Violation: importing a layer
        # with a LOWER rank number (i.e. higher in the architecture).
        if direction == "top-down":
            # src imports dst.  Allowed if dst_rank >= src_rank (same or below).
            # Violation if dst_rank < src_rank (dst is above src).
            if dst_rank >= src_rank:
                continue  # allowed: importing from same level or below
        else:
            # bottom-up: allowed if dst_rank <= src_rank
            if dst_rank <= src_rank:
                continue

        # Check explicit exceptions
        if _is_allowed_cross(src_name, dst_name, allowed_cross):
            continue

        severity = str(cfg.get("severity", "high")).lower()
        findings.append(
            Finding(
                policy_id="CK-ARCH-LAYER-DIRECTION",
                title=f"Layer violation: {src_name} → {dst_name}",
                severity=severity,
                confidence="high",
                why_it_matters=(
                    f"Layer '{src_name}' imports from '{dst_name}' which is "
                    f"above it in the architecture.  Upward imports collapse "
                    f"layer separation and create hidden coupling."
                ),
                evidence=[
                    Evidence(
                        file=normalize_path(edge.src_file),
                        line=edge.line,
                        snippet=clamp_snippet(f"import {edge.module}"),
                        note=f"{src_name} (layer {src_rank}) → {dst_name} (layer {dst_rank})",
                    )
                ],
                fix_options=[
                    f"Move the shared code to a lower layer or create an interface in '{dst_name}'.",
                    "Add an explicit exception in allowed_cross_layer with a documented reason.",
                ],
                verification=[f"python -m compileall -q {edge.src_file}"],
                metadata={
                    "src_layer": src_name,
                    "dst_layer": dst_name,
                    "module": edge.module,
                    "dst_file": edge.dst_file,
                },
            )
        )

    return findings


def _classify(
    file_path: str, layers: List[Tuple[str, List[str], int]]
) -> Tuple[str, int] | None:
    """Return (layer_name, rank) for a file, or None if it doesn't match any layer."""
    normed = file_path.replace("\\", "/")
    for name, patterns, rank in layers:
        if matches_any(normed, patterns):
            return (name, rank)
    return None


def _is_allowed_cross(
    src_layer: str, dst_layer: str, allowed: List[Dict[str, Any]]
) -> bool:
    for entry in allowed:
        if str(entry.get("from", "")) == src_layer and str(entry.get("to", "")) == dst_layer:
            return True
    return False
