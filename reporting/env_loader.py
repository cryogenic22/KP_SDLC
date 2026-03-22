"""Load .env file into os.environ.

Zero-dependency .env loader. Reads KEY=VALUE pairs from .env files,
skipping comments (#) and blank lines. Does NOT override existing
environment variables (env vars take precedence over .env file).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def load_env(env_path: Optional[str] = None) -> dict:
    """Load .env file and return the parsed values.

    Search order for .env:
    1. Explicit path (if provided)
    2. Current working directory
    3. KP_SDLC repo root (parent of reporting/)

    Returns dict of loaded key-value pairs (for logging/debugging).
    """
    if env_path:
        paths = [Path(env_path)]
    else:
        paths = [
            Path.cwd() / ".env",
            Path(__file__).resolve().parents[1] / ".env",
        ]

    loaded = {}
    for p in paths:
        if p.is_file():
            loaded = _parse_env_file(p)
            break

    return loaded


def _parse_env_file(path: Path) -> dict:
    """Parse a .env file and set values in os.environ."""
    loaded = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments and blank lines
            if not line or line.startswith("#"):
                continue
            # Split on first =
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # Don't override existing env vars
            if key and value and key not in os.environ:
                os.environ[key] = value
                loaded[key] = value
    return loaded
