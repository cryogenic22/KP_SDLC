from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from cathedral_keeper.models import Finding


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    root: Path
    target_paths_file: Path
    target_rel_paths: List[str]


def parse_enabled_integrations(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    cfg = dict(raw.get("integrations", {}) or {})
    out: Dict[str, Dict[str, Any]] = {}
    for key, val in cfg.items():
        if not isinstance(val, dict):
            continue
        if not bool(val.get("enabled", False)):
            continue
        out[str(key)] = val
    return out

