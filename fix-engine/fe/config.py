"""Configuration loader with 3-layer merge.

Priority (highest wins):
    CLI overrides  >  config file  >  built-in defaults

The built-in defaults mirror ``fix-engine.config.json`` so the engine
works out of the box without any file on disk.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Built-in defaults (same structure as fix-engine.config.json)
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Any] = {
    "fix_engine": {
        "enabled": True,
        "auto_apply_threshold": 0.95,
        "categories": {
            "safe": {"auto_apply": True},
            "review": {"auto_apply": False, "suggest": True},
            "manual": {"auto_apply": False, "suggest": False},
        },
        "disabled_fixes": [],
        "sarif": {
            "include_fixes": True,
            "include_code_flows": True,
            "tool_name": "KP_SDLC Quality Gate",
            "tool_version": "1.0.0",
        },
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*.

    Scalar values in *override* replace those in *base*.  Dicts are
    merged recursively.  Lists in *override* replace (not extend) those
    in *base*.
    """
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _flatten_set(d: dict, prefix: str = "") -> dict:
    """Set nested dict keys using dotted *prefix* path.

    >>> _flatten_set({}, "a.b.c")
    This is an internal helper used by :func:`_apply_dotted_overrides`.
    """
    return d


def _apply_dotted_overrides(config: dict, overrides: dict) -> dict:
    """Apply *overrides* whose keys may be dot-separated paths.

    For example ``{"fix_engine.auto_apply_threshold": 0.8}`` sets
    ``config["fix_engine"]["auto_apply_threshold"]`` to ``0.8``.

    Plain (non-dotted) keys are merged with :func:`_deep_merge`.
    """
    plain: dict = {}
    dotted: dict = {}
    for key, value in overrides.items():
        if "." in key:
            dotted[key] = value
        else:
            plain[key] = value

    result = _deep_merge(config, plain)

    for dotted_key, value in dotted.items():
        parts = dotted_key.split(".")
        target = result
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(
    config_path: Optional[Path] = None,
    cli_overrides: Optional[dict] = None,
) -> dict:
    """Load configuration with 3-layer merge.

    1. Start with built-in ``_DEFAULTS``.
    2. If *config_path* is given (and exists), deep-merge the JSON contents.
    3. If *cli_overrides* is given, apply them on top (supports dotted keys).

    Returns
    -------
    dict
        The fully-merged configuration dictionary.
    """
    config = copy.deepcopy(_DEFAULTS)

    # Layer 2: file overrides
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as fh:
                file_config = json.load(fh)
            config = _deep_merge(config, file_config)

    # Layer 3: CLI overrides
    if cli_overrides:
        config = _apply_dotted_overrides(config, cli_overrides)

    return config
