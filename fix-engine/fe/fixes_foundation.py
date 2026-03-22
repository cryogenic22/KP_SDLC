"""Foundation-level fix functions.

Eight safe, high-confidence fixers for the most common Python lint rules.
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
# 1. bare_except
# ---------------------------------------------------------------------------

@register_fix("bare_except", confidence=1.0, category="safe")
def fix_bare_except(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace bare ``except:`` with ``except Exception:``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match "except:" that is NOT "except <Something>:"
    pattern = re.compile(r"^(\s*)except\s*:\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    replacement = f"{indent}except Exception:\n"
    return FixPatch(
        rule_id="bare_except",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "A bare ``except:`` catches BaseException (including "
            "SystemExit and KeyboardInterrupt). Narrow it to "
            "``except Exception:`` so only program errors are caught."
        ),
        confidence=1.0,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 2. mutable_default
# ---------------------------------------------------------------------------

@register_fix("mutable_default", confidence=0.95, category="safe")
def fix_mutable_default(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace mutable default argument with None and add a guard."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Matches e.g. "def f(x=[]):" or "def f(x={}):"
    pattern = re.compile(
        r"^(\s*def\s+\w+\s*\(.*?)(\w+)\s*=\s*(\[\]|\{\})(.*\)\s*:\s*)$"
    )
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    prefix = m.group(1)
    param = m.group(2)
    mutable_literal = m.group(3)
    suffix = m.group(4)

    # Build replacement: change default to None, add guard line
    indent_match = re.match(r"^(\s*)", line)
    body_indent = (indent_match.group(1) if indent_match else "") + "    "
    new_def = f"{prefix}{param}=None{suffix}\n"
    guard = f"{body_indent}if {param} is None:\n{body_indent}    {param} = {mutable_literal}\n"
    replacement = new_def + guard

    return FixPatch(
        rule_id="mutable_default",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "Mutable default arguments are shared across all calls. "
            "Use ``None`` as the default and create the mutable inside "
            "the function body."
        ),
        confidence=0.95,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 3. no_debug_statements
# ---------------------------------------------------------------------------

@register_fix("no_debug_statements", confidence=0.95, category="safe")
def fix_no_debug_statements(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Delete debug statements such as breakpoint() or print("DEBUG...")."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    stripped = line.strip()
    is_debug = (
        stripped.startswith("breakpoint(")
        or stripped == "breakpoint()"
        or re.match(r'^print\s*\(\s*["\']DEBUG', stripped)
    )
    if not is_debug:
        return None

    return FixPatch(
        rule_id="no_debug_statements",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement="",
        explanation=(
            "Debug statements (breakpoint(), print(\"DEBUG ...\")) "
            "should not ship to production. Removing the line."
        ),
        confidence=0.95,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 4. unused_import
# ---------------------------------------------------------------------------

@register_fix("unused_import", confidence=1.0, category="safe")
def fix_unused_import(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Delete an unused import line."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    stripped = line.strip()
    if not (stripped.startswith("import ") or stripped.startswith("from ")):
        return None

    return FixPatch(
        rule_id="unused_import",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement="",
        explanation=(
            "This import is unused. Removing it reduces clutter and "
            "avoids accidental coupling."
        ),
        confidence=1.0,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 5. trailing_whitespace
# ---------------------------------------------------------------------------

@register_fix("trailing_whitespace", confidence=1.0, category="safe")
def fix_trailing_whitespace(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Strip trailing whitespace from a line."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    stripped = line.rstrip()
    # Only fix if there actually is trailing whitespace (ignoring newline)
    line_no_newline = line.rstrip("\n").rstrip("\r")
    if line_no_newline == stripped:
        return None

    replacement = stripped + "\n"
    return FixPatch(
        rule_id="trailing_whitespace",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation="Trailing whitespace removed for cleaner diffs and style consistency.",
        confidence=1.0,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 6. equality_none
# ---------------------------------------------------------------------------

@register_fix("equality_none", confidence=1.0, category="safe")
def fix_equality_none(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``== None`` / ``!= None`` with ``is None`` / ``is not None``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    new_line = line
    new_line = re.sub(r'==\s*None\b', 'is None', new_line)
    new_line = re.sub(r'!=\s*None\b', 'is not None', new_line)

    if new_line == line:
        return None

    return FixPatch(
        rule_id="equality_none",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            "PEP 8 recommends ``is None`` / ``is not None`` instead of "
            "``== None`` / ``!= None`` because None is a singleton."
        ),
        confidence=1.0,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 7. equality_true_false
# ---------------------------------------------------------------------------

@register_fix("equality_true_false", confidence=0.95, category="safe")
def fix_equality_true_false(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Simplify ``x == True`` to ``x`` and ``x == False`` to ``not x``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    new_line = line
    # x == True  -> x
    new_line = re.sub(r'(\w+)\s*==\s*True\b', r'\1', new_line)
    # x == False -> not x
    new_line = re.sub(r'(\w+)\s*==\s*False\b', r'not \1', new_line)

    if new_line == line:
        return None

    return FixPatch(
        rule_id="equality_true_false",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            "Comparing to True/False with ``==`` is redundant. "
            "Use the value directly (``x``) or negate it (``not x``)."
        ),
        confidence=0.95,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 8. empty_return
# ---------------------------------------------------------------------------

@register_fix("empty_return", confidence=1.0, category="safe")
def fix_empty_return(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace bare ``return`` with ``return None`` for explicitness."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    pattern = re.compile(r"^(\s*)return\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    replacement = f"{indent}return None\n"
    return FixPatch(
        rule_id="empty_return",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "An explicit ``return None`` is clearer about intent than a "
            "bare ``return`` and makes the code easier to read."
        ),
        confidence=1.0,
        category="safe",
    )
