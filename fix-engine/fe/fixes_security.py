"""Security-focused fix functions.

Three fixers addressing common security anti-patterns.
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
# 1. no_type_escape
# ---------------------------------------------------------------------------

@register_fix("no_type_escape", confidence=0.7, category="review")
def fix_no_type_escape(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Remove ``# type: ignore`` comments from a line."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    if "# type: ignore" not in line:
        return None

    # Remove the comment (and optional trailing bracket specification)
    replacement = re.sub(r"\s*#\s*type:\s*ignore(\[[\w\-,\s]*\])?\s*", "", line)
    if not replacement.endswith("\n"):
        replacement += "\n"

    return FixPatch(
        rule_id="no_type_escape",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "``# type: ignore`` suppresses type-checker warnings and can "
            "mask real bugs. Remove the suppression and fix the underlying "
            "type issue instead."
        ),
        confidence=0.7,
        category="review",
    )


# ---------------------------------------------------------------------------
# 2. command_injection
# ---------------------------------------------------------------------------

@register_fix("command_injection", confidence=0.8, category="review")
def fix_command_injection(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``os.system(cmd)`` with ``subprocess.run(cmd.split(), check=True)``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    pattern = re.compile(r"^(\s*)os\.system\((.+)\)\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    arg = m.group(2)
    replacement = f"{indent}subprocess.run({arg}.split(), check=True)\n"

    return FixPatch(
        rule_id="command_injection",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "``os.system()`` passes its argument through the shell, which "
            "is vulnerable to command injection. ``subprocess.run()`` with "
            "a list argument avoids shell interpretation."
        ),
        confidence=0.8,
        category="review",
    )


# ---------------------------------------------------------------------------
# 3. assert_in_production
# ---------------------------------------------------------------------------

@register_fix("assert_in_production", confidence=0.85, category="review")
def fix_assert_in_production(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``assert cond`` with ``if not cond: raise ValueError(...)``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    pattern = re.compile(r"^(\s*)assert\s+(.+)$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    rest = m.group(2)

    # Split on first comma to get condition and optional message
    if "," in rest:
        condition, message = rest.split(",", 1)
        condition = condition.strip()
        message = message.strip()
    else:
        condition = rest.strip()
        message = f'\"Assertion failed: {condition}\"'

    replacement = (
        f"{indent}if not ({condition}):\n"
        f"{indent}    raise ValueError({message})\n"
    )

    return FixPatch(
        rule_id="assert_in_production",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "``assert`` statements are stripped when Python runs with "
            "``-O`` (optimised mode). Use an explicit ``if`` / ``raise`` "
            "for checks that must always execute."
        ),
        confidence=0.85,
        category="review",
    )
