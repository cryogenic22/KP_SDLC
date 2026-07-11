"""Filesystem readers and tolerant coercers for untrusted repository artifacts.

Every Observatory projection reads optional repository artifacts (settings, MCP
config, checkpoint ledgers, gate reports). A missing, unreadable, or malformed
artifact is a normal, expected state — never an exception the caller must guard.

``read_json``/``read_jsonl`` guard the *outer* shape, but a well-formed JSON
object can still carry a garbage *nested* value (a ``stats`` that is a list, a
``turns`` that is the string ``"lots"``, a ``literal_fidelity`` of ``"n/a"``).
The ``as_dict``/``as_int``/``as_float`` coercers extend the same fail-closed
guarantee to those nested reads, so one corrupt ledger row degrades a panel
instead of raising through the snapshot and 500-ing the whole dashboard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | None:
    """Return a decoded JSON object, or ``None`` when it is absent or unusable.

    ``None`` (not ``{}``) marks "no artifact here" so callers can distinguish a
    missing report from an empty one; callers that want a mapping use
    ``read_json(path) or {}``.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Return the object records of a JSON Lines file, skipping unusable lines.

    A missing file yields ``[]``; a corrupt line is dropped rather than aborting
    the whole read, so one bad append never blinds a projection to the rest.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def as_dict(value: Any) -> dict[str, Any]:
    """The value if it is a mapping, else an empty dict — never raises on the wrong type."""
    return value if isinstance(value, dict) else {}


def as_int(value: Any, default: int = 0) -> int:
    """Best-effort int; a missing or non-numeric value collapses to ``default``."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any) -> float | None:
    """Best-effort float, or ``None`` when the value is absent or non-numeric.

    ``None`` is a distinct signal — a value that was supplied but is not a number
    (e.g. a ``literal_fidelity`` of ``"n/a"``) is worse than a low number, and the
    caller surfaces it as a finding rather than crashing on the cast.
    """
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
