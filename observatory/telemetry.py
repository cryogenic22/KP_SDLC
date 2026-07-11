"""Harness telemetry adapter contract and Claude Code capability discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from .events import read_events
from .sources import read_json


class TelemetryAdapter(Protocol):
    adapter_id: str

    def probe(self) -> dict[str, Any]: ...


# Canonical capability -> the hook event types that evidence it. Used to derive
# the three-state view (observed / supported-but-no-evidence / unavailable) the
# dashboard renders; the exact configured booleans stay in ``capabilities``.
_CAPABILITY_EVENTS = {
    "session_lifecycle": ("SessionStart", "Stop", "SessionEnd"),
    "tool_lifecycle": ("PreToolUse", "PostToolUse", "PostToolUseFailure"),
    "tool_failures": ("PostToolUseFailure",),
    "permissions": ("PermissionDenied", "Notification"),
    "subagents": ("SubagentStart", "SubagentStop"),
    "compaction": ("PreCompact", "PostCompact"),
}


def _configured_events(settings: dict[str, Any]) -> set[str]:
    hooks = settings.get("hooks") or {}
    return {str(name) for name, entries in hooks.items() if isinstance(entries, list) and entries}


def _capability_states(capabilities: dict[str, bool], observed: set[str]) -> dict[str, str]:
    """Classify each canonical capability by how much we actually know.

    ``unavailable`` — not configured on this harness; ``supported`` — configured
    but no matching event has been observed yet; ``observed`` — configured and a
    real event proves it. A configured-but-silent capability must never read as
    healthy, so it stays distinct from an observed one.
    """
    states = {}
    for name, events in _CAPABILITY_EVENTS.items():
        if not capabilities.get(name):
            states[name] = "unavailable"
        elif any(event in observed for event in events):
            states[name] = "observed"
        else:
            states[name] = "supported"
    return states


class ClaudeCodeTelemetryAdapter:
    """Translate evolving Claude hook coverage into canonical capabilities."""

    adapter_id = "claude-code/hooks@1"

    def __init__(self, root: Path):
        self.root = root.resolve()

    def probe(self) -> dict[str, Any]:
        settings = read_json(self.root / ".claude" / "settings.json") or {}
        configured = _configured_events(settings)
        observed_events = read_events(self.root, limit=1000)
        observed = {str(event.get("event_type") or "Unknown") for event in observed_events}
        capabilities = {
            "session_lifecycle": bool(configured & {"SessionStart", "Stop", "SessionEnd"}),
            "tool_lifecycle": "PreToolUse" in configured and bool(configured & {"PostToolUse", "PostToolUseFailure"}),
            "tool_failures": "PostToolUseFailure" in configured,
            "permissions": bool(configured & {"PermissionDenied", "Notification"}),
            "subagents": "SubagentStart" in configured and "SubagentStop" in configured,
            "compaction": bool(configured & {"PreCompact", "PostCompact"}),
            "live_events_observed": bool(observed_events),
        }
        return {
            "adapter": self.adapter_id,
            "harness": "claude-code",
            "detected": bool(settings),
            "capabilities": capabilities,
            "capability_states": _capability_states(capabilities, observed),
            "configured_event_types": sorted(configured),
            "observed_event_types": sorted(observed),
            "unknown_observed_event_types": sorted(observed - configured),
            "event_count": len(observed_events),
            "limitations": [
                "Exact provider context-window utilization is unavailable from hooks alone."
            ],
        }

