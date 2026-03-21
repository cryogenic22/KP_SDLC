"""CK-ARCH-SERVICE-BOUNDARIES — Service Boundary Coherence.

Defines service boundaries (groups of modules forming a logical service)
and ensures cross-service imports only go through defined interface modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cathedral_keeper.models import Evidence, Finding, clamp_snippet, normalize_path
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_graph import build_import_graph, build_module_index


def check_service_boundaries(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg
    services_cfg = list(inner_cfg.get("services") or [])
    if not services_cfg:
        return []

    allow_shared = list(inner_cfg.get("allow_shared") or [])

    # Build service definitions: list of ServiceDef
    services: List[_ServiceDef] = []
    for entry in services_cfg:
        name = str(entry.get("name", ""))
        svc_root = str(entry.get("root", "")).replace("\\", "/").rstrip("/")
        public = [str(p).replace("\\", "/") for p in (entry.get("public_interface") or [])]
        if name and svc_root:
            services.append(_ServiceDef(name=name, root=svc_root, public_interface=public))

    if not services:
        return []

    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    severity = str(cfg.get("severity", "high")).lower()
    findings: List[Finding] = []

    for edge in graph.edges:
        src_norm = normalize_path(edge.src_file)
        dst_norm = normalize_path(edge.dst_file)

        src_svc = _find_service(src_norm, services)
        dst_svc = _find_service(dst_norm, services)

        # Skip if not cross-service
        if src_svc is None or dst_svc is None:
            continue
        if src_svc.name == dst_svc.name:
            continue

        # Allow shared modules
        if matches_any(dst_norm, allow_shared):
            continue

        # Check if destination is in the target service's public interface
        if _is_public(dst_norm, dst_svc):
            continue

        findings.append(
            Finding(
                policy_id="CK-ARCH-SERVICE-BOUNDARIES",
                title=f"Cross-service internal import: {src_svc.name} → {dst_svc.name}",
                severity=severity,
                confidence="high",
                why_it_matters=(
                    f"Service '{src_svc.name}' imports an internal module of "
                    f"'{dst_svc.name}' instead of going through its public interface. "
                    f"Direct cross-service imports create hidden coupling that makes "
                    f"it impossible to extract services or reason about failure boundaries."
                ),
                evidence=[
                    Evidence(
                        file=src_norm,
                        line=edge.line,
                        snippet=clamp_snippet(f"import {edge.module}"),
                        note=(
                            f"{src_svc.name} → {dst_svc.name} internal "
                            f"(target: {dst_norm})"
                        ),
                    )
                ],
                fix_options=[
                    f"Move the needed functionality into {dst_svc.name}'s public interface.",
                    f"Add '{dst_norm}' to {dst_svc.name}'s public_interface list if this is intentional.",
                    f"Move shared code to a shared module matching allow_shared patterns.",
                ],
                verification=[f"python -m compileall -q {edge.src_file}"],
                metadata={
                    "src_service": src_svc.name,
                    "dst_service": dst_svc.name,
                    "dst_file": dst_norm,
                    "module": edge.module,
                    "public_interface": dst_svc.public_interface,
                },
            )
        )

    return findings


# ── internal helpers ───────────────────────────────────────────────

class _ServiceDef:
    __slots__ = ("name", "root", "public_interface")

    def __init__(self, name: str, root: str, public_interface: List[str]) -> None:
        self.name = name
        self.root = root.replace("\\", "/").rstrip("/")
        self.public_interface = [p.replace("\\", "/") for p in public_interface]


def _find_service(file_path: str, services: List[_ServiceDef]) -> Optional[_ServiceDef]:
    """Return the service a file belongs to, or None."""
    normed = file_path.replace("\\", "/")
    for svc in services:
        # A file belongs to a service if its path starts with the service root
        if normed.startswith(svc.root + "/") or normed == svc.root:
            return svc
    return None


def _is_public(file_path: str, svc: _ServiceDef) -> bool:
    """Check if a file is in the service's public interface."""
    normed = file_path.replace("\\", "/")
    for pub in svc.public_interface:
        # Exact match or glob match
        if normed == pub or matches_any(normed, [pub]):
            return True
    return False
