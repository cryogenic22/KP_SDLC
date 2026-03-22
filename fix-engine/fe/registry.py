"""Decorator-based fix registry.

Fix functions are registered by rule_id. Each decorated function
receives finding metadata and returns a FixPatch (or None).
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

_FIX_REGISTRY: Dict[str, Callable] = {}


def register_fix(
    rule_id: str, confidence: float = 0.95, category: str = "safe"
) -> Callable:
    """Decorator to register a fix function for a given rule_id."""

    def decorator(fn: Callable) -> Callable:
        fn._fix_meta = {
            "rule_id": rule_id,
            "confidence": confidence,
            "category": category,
        }
        _FIX_REGISTRY[rule_id] = fn
        return fn

    return decorator


def get_fix(rule_id: str) -> Optional[Callable]:
    """Return the fix function for *rule_id*, or None."""
    return _FIX_REGISTRY.get(rule_id)


def list_fixable_rules() -> List[str]:
    """Return a sorted list of all registered rule ids."""
    return sorted(_FIX_REGISTRY.keys())


def get_fix_meta(rule_id: str) -> Optional[dict]:
    """Return the metadata dict attached by the decorator, or None."""
    fn = _FIX_REGISTRY.get(rule_id)
    return getattr(fn, "_fix_meta", None) if fn else None
