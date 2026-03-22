"""AI / LLM-specific fix functions.

Three fixers for common LLM integration anti-patterns.
Every function follows the signature:
    (finding: dict, file_content: str, config: dict) -> FixPatch | None
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from .registry import register_fix
from .types import FixPatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_line(file_content: str, line_no: int) -> Optional[str]:
    """Return the 1-based *line_no* from *file_content*, or None."""
    lines = file_content.splitlines(keepends=True)
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return None


# ---------------------------------------------------------------------------
# 1. unbounded_tokens
# ---------------------------------------------------------------------------

@register_fix("unbounded_tokens", confidence=0.85, category="review")
def fix_unbounded_tokens(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``max_tokens=4096`` to an LLM API call that lacks a token limit."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    if "max_tokens" in line:
        return None

    # Match common LLM call patterns like: .create(...), .complete(...), .generate(...)
    pattern = re.compile(
        r"(\.(?:create|complete|generate|chat|completions\.create)\s*\([^)]*?)(\)\s*)$"
    )
    m = pattern.search(line.rstrip("\n"))
    if not m:
        return None

    before_close = m.group(1)
    close = m.group(2)
    replacement_line = line[:m.start()] + before_close + ", max_tokens=4096" + close + "\n"

    return FixPatch(
        rule_id="unbounded_tokens",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement_line,
        explanation=(
            "LLM calls without ``max_tokens`` can generate unbounded output, "
            "leading to high costs and latency. Setting a limit is a best practice."
        ),
        confidence=0.85,
        category="review",
    )


# ---------------------------------------------------------------------------
# 2. llm_timeout
# ---------------------------------------------------------------------------

@register_fix("llm_timeout", confidence=0.85, category="review")
def fix_llm_timeout(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``timeout=30`` to an LLM API call that lacks a timeout."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    if "timeout" in line:
        return None

    pattern = re.compile(
        r"(\.(?:create|complete|generate|chat|completions\.create)\s*\([^)]*?)(\)\s*)$"
    )
    m = pattern.search(line.rstrip("\n"))
    if not m:
        return None

    before_close = m.group(1)
    close = m.group(2)
    replacement_line = line[:m.start()] + before_close + ", timeout=30" + close + "\n"

    return FixPatch(
        rule_id="llm_timeout",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement_line,
        explanation=(
            "LLM API calls without a timeout can hang indefinitely. "
            "Adding ``timeout=30`` prevents resource exhaustion."
        ),
        confidence=0.85,
        category="review",
    )


# ---------------------------------------------------------------------------
# 3. missing_await
# ---------------------------------------------------------------------------

@register_fix("missing_await", confidence=0.95, category="safe")
def fix_missing_await(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``await`` before an async call that is missing it."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Already has await
    if "await " in line:
        return None

    # The finding should tell us what call is missing await.
    # We look for a function call pattern that should be awaited.
    # Match: <indent><optional var = > <call>(...)
    pattern = re.compile(r"^(\s*)((?:\w+\s*=\s*)?)(\w[\w.]*\([^)]*\))\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    assignment = m.group(2)
    call = m.group(3)
    replacement = f"{indent}{assignment}await {call}\n"

    return FixPatch(
        rule_id="missing_await",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "This async function call is missing ``await``. Without it, "
            "the coroutine is created but never executed, which is almost "
            "certainly a bug."
        ),
        confidence=0.95,
        category="safe",
    )
