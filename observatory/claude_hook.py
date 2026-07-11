"""Claude Code command-hook adapter. Reads one payload from stdin and exits quickly."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from .events import append_event, normalize_claude_hook
except ImportError:  # Direct execution: python observatory/claude_hook.py
    from events import append_event, normalize_claude_hook


def main() -> int:
    # Kill switch: with default-on capture, any contributor can opt out for a
    # session without editing shared settings.json. Fail-safe no-op, exit 0.
    if os.environ.get("OBSERVATORY_DISABLE") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook payload must be a JSON object")
        capture_inputs = os.environ.get("OBSERVATORY_CAPTURE_INPUTS") == "1"
        event = normalize_claude_hook(payload, capture_inputs=capture_inputs)
        append_event(Path(payload.get("cwd") or Path.cwd()), event)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[observatory] hook capture failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

