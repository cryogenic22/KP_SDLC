from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class CKConfig:
    root: Path
    raw: Dict[str, Any]

    @property
    def policies(self) -> Dict[str, Any]:
        return dict(self.raw.get("policies", {}) or {})

    @property
    def paths(self) -> Dict[str, Any]:
        return dict(self.raw.get("paths", {}) or {})

    @property
    def reporting(self) -> Dict[str, Any]:
        return dict(self.raw.get("reporting", {}) or {})

    @property
    def thresholds(self) -> Dict[str, Any]:
        return dict(self.raw.get("thresholds", {}) or {})

    @property
    def python_roots_config(self) -> list:
        """Return the configured python_roots list, or empty for auto-discovery.

        Each entry is a dict with 'prefix' and 'path' keys.
        Example: [{"prefix": "src", "path": "myproject/src"}]
        """
        return list(self.raw.get("python_roots", []) or [])


def load_config(*, root: Path, config_path: Optional[Path]) -> CKConfig:
    script_dir = Path(__file__).resolve().parents[1]
    defaults_path = script_dir / "cathedral-keeper.config.json"
    base = _read_json(defaults_path) if defaults_path.exists() else {}

    override = _read_json(root / ".cathedral-keeper.json") if (root / ".cathedral-keeper.json").exists() else {}
    if config_path and config_path.exists():
        override = _deep_merge(override, _read_json(config_path))

    merged = _deep_merge(base, override)
    return CKConfig(root=root, raw=merged)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for k, v in override.items():
        existing = out.get(k)
        if isinstance(v, dict) and isinstance(existing, dict):
            out[k] = _deep_merge(existing, v)
        else:
            out[k] = v
    return out

