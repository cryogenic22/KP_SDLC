"""Merge Observatory command hooks into a project without replacing existing hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOOK_COMMAND = "python observatory/claude_hook.py"
HOOK_EVENTS = (
    "SessionStart",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionDenied",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PostCompact",
    "Stop",
    "SessionEnd",
)


def install(root: Path) -> tuple[Path, list[str]]:
    settings_path = root.resolve() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError(f"{settings_path} must contain a JSON object")
    else:
        settings = {}
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude settings 'hooks' must be a JSON object")

    added = []
    for event_name in HOOK_EVENTS:
        entries = hooks.setdefault(event_name, [])
        if not isinstance(entries, list):
            raise ValueError(f"Claude hook '{event_name}' must be a JSON array")
        if _has_command(entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 5}]})
        added.append(event_name)

    temporary = settings_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temporary.replace(settings_path)
    return settings_path, added


def _has_command(entries: list[Any]) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == HOOK_COMMAND:
                return True
    return False

