"""Normalize Claude Code hooks into a small, privacy-conscious event contract."""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENT_SCHEMA = "agent-observatory/event@1"
_SENSITIVE_PARTS = ("api_key", "authorization", "cookie", "credential", "password", "secret", "token")
_SAFE_FIELDS = (
    "agent_id",
    "agent_type",
    "duration_ms",
    "error",
    "is_interrupt",
    "notification_type",
    "permission_mode",
    "source",
    "tool_name",
    "tool_use_id",
    "trigger",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if any(part in key.lower() for part in _SENSITIVE_PARTS):
        return "<redacted>"
    if depth >= 4:
        return "<truncated>"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k), depth=depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value if len(value) <= 512 else value[:509] + "..."
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:512]


def normalize_claude_hook(payload: dict[str, Any], *, capture_inputs: bool = False,
                          received_at: str | None = None) -> dict[str, Any]:
    """Return the stable event shape consumed by the health model and UI.

    Tool inputs are opt-in because commands and MCP arguments can contain secrets.
    Even when enabled, sensitive-looking keys are redacted and values are bounded.
    """
    event_type = str(payload.get("hook_event_name") or "Unknown")
    session_id = str(payload.get("session_id") or "unknown")
    timestamp = received_at or _now_iso()
    details = {field: _redact(payload[field], key=field) for field in _SAFE_FIELDS if field in payload}
    if capture_inputs and "tool_input" in payload:
        details["tool_input"] = _redact(payload["tool_input"], key="tool_input")
    identity = json.dumps(
        [session_id, event_type, payload.get("tool_use_id"), timestamp],
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": EVENT_SCHEMA,
        "id": hashlib.sha256(identity).hexdigest()[:20],
        "timestamp": timestamp,
        "source": "claude-code",
        "event_type": event_type,
        "session_id": session_id,
        "cwd": str(payload.get("cwd") or ""),
        "details": details,
    }


def append_jsonl(target: Path, payload: dict[str, Any]) -> Path:
    """Append one bounded JSON record. O_APPEND keeps concurrent writes intact;
    0600 keeps the ledger readable only by its owner. Single-sourced so every
    Observatory ledger inherits the same durability and permission posture."""
    target.parent.mkdir(parents=True, exist_ok=True)
    record = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    descriptor = os.open(target, flags, 0o600)
    try:
        os.write(descriptor, record.encode("utf-8"))
    finally:
        os.close(descriptor)
    return target


def append_event(root: Path, event: dict[str, Any]) -> Path:
    """Append one normalized event to this repo's event ledger."""
    return append_jsonl(root.resolve() / ".observatory" / "events.jsonl", event)


def read_events(root: Path, *, limit: int = 500) -> list[dict[str, Any]]:
    path = root.resolve() / ".observatory" / "events.jsonl"
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=max(1, limit))
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("schema") == EVENT_SCHEMA:
                rows.append(value)
    return list(rows)

