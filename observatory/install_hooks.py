"""Merge Observatory command hooks into a project without replacing existing hooks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HOOK_EXECUTABLE = "python"
HOOK_SCRIPT = "${CLAUDE_PROJECT_DIR}/observatory/claude_hook.py"
HOOK_ARGS = (HOOK_SCRIPT,)
_LEGACY_HOOK_COMMANDS = {
    "python observatory/claude_hook.py",
    "python -P observatory/claude_hook.py",
}
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
        if _normalize_handlers(entries):
            continue
        entries.append({"hooks": [_hook_handler()]})
        added.append(event_name)

    temporary = settings_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    temporary.replace(settings_path)
    return settings_path, added


def _hook_handler() -> dict[str, Any]:
    return {
        "type": "command",
        "command": HOOK_EXECUTABLE,
        "args": list(HOOK_ARGS),
        "timeout": 5,
    }


def _is_observatory_handler(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    if hook.get("command") in _LEGACY_HOOK_COMMANDS:
        return True
    return (
        hook.get("command") == HOOK_EXECUTABLE
        and hook.get("args") == list(HOOK_ARGS)
    )


def _normalize_handlers(entries: list[Any]) -> bool:
    """Migrate one Observatory handler and discard only its duplicates."""
    found = False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        configured = entry.get("hooks")
        if not isinstance(configured, list):
            continue
        normalized = []
        for hook in configured:
            if not _is_observatory_handler(hook):
                normalized.append(hook)
                continue
            if not found:
                normalized.append(_hook_handler())
                found = True
        entry["hooks"] = normalized
    return found

