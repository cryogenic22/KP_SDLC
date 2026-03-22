"""Additional fix functions to reach the PRD 35+ target.

Nine fixers covering dict access patterns, f-string upgrades, docstrings,
magic numbers, error types, global variables, hardcoded models, and
FastAPI response models.

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
# 1. dict_get_default
# ---------------------------------------------------------------------------

@register_fix("dict_get_default", confidence=0.9, category="safe")
def fix_dict_get_default(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``d[k] if k in d else v`` with ``d.get(k, v)``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Pattern: <dict>[<key>] if <key> in <dict> else <default>
    pattern = re.compile(
        r"(\w+)\[(\w+)\]\s+if\s+\2\s+in\s+\1\s+else\s+(.+)"
    )
    m = pattern.search(line)
    if not m:
        return None

    dict_name = m.group(1)
    key_name = m.group(2)
    default_val = m.group(3).rstrip()

    replacement = line[:m.start()] + f"{dict_name}.get({key_name}, {default_val})" + line[m.end():]
    # Ensure trailing newline
    if not replacement.endswith("\n"):
        replacement += "\n"

    return FixPatch(
        rule_id="dict_get_default",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "The ternary ``d[k] if k in d else v`` pattern duplicates the "
            "key lookup. Use ``d.get(k, v)`` for clarity and a single lookup."
        ),
        confidence=0.9,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 2. f_string_upgrade
# ---------------------------------------------------------------------------

@register_fix("f_string_upgrade", confidence=0.9, category="safe")
def fix_f_string_upgrade(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Upgrade ``.format()`` and ``%`` string formatting to f-strings."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    new_line = line

    # Pattern 1: "...{}...".format(args) -> f"...{args}..."
    # Match quoted string with {} placeholders followed by .format(...)
    fmt_pattern = re.compile(
        r"""(["'])([^"']*?\{\}[^"']*?)\1\.format\(([^)]+)\)"""
    )
    fmt_match = fmt_pattern.search(new_line)
    if fmt_match:
        quote = fmt_match.group(1)
        template = fmt_match.group(2)
        args_str = fmt_match.group(3)
        args = [a.strip() for a in args_str.split(",")]

        # Replace each {} with the corresponding argument
        result = template
        for arg in args:
            result = result.replace("{}", "{" + arg + "}", 1)

        replacement_str = f'f{quote}{result}{quote}'
        new_line = new_line[:fmt_match.start()] + replacement_str + new_line[fmt_match.end():]

    # Pattern 2: "%s" % expr -> f"{expr}"
    pct_pattern = re.compile(
        r"""(["'])([^"']*?%s[^"']*?)\1\s*%\s*(\w+)"""
    )
    pct_match = pct_pattern.search(new_line)
    if pct_match:
        quote = pct_match.group(1)
        template = pct_match.group(2)
        expr = pct_match.group(3)

        # Replace %s with {expr}
        result = template.replace("%s", "{" + expr + "}", 1)
        replacement_str = f'f{quote}{result}{quote}'
        new_line = new_line[:pct_match.start()] + replacement_str + new_line[pct_match.end():]

    if new_line == line:
        return None

    if not new_line.endswith("\n"):
        new_line += "\n"

    return FixPatch(
        rule_id="f_string_upgrade",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            "f-strings (PEP 498) are more readable and often faster than "
            "``.format()`` or ``%`` formatting. Prefer ``f'...'`` style."
        ),
        confidence=0.9,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 3. missing_docstring
# ---------------------------------------------------------------------------

@register_fix("missing_docstring", confidence=0.9, category="safe")
def fix_missing_docstring(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Insert a placeholder docstring for a function missing one."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match a function definition line
    pattern = re.compile(r"^(\s*)def\s+\w+\s*\(.*\)\s*:\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    body_indent = indent + "    "

    # Check that the next line is NOT already a docstring
    next_line = _get_line(file_content, line_no + 1)
    if next_line and '"""' in next_line.strip():
        return None

    replacement = line.rstrip("\n") + "\n" + f'{body_indent}"""TODO: Add docstring."""\n'

    return FixPatch(
        rule_id="missing_docstring",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "Every public function should have a docstring (PEP 257). "
            "Adding a TODO placeholder as a reminder to document this function."
        ),
        confidence=0.9,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 4. no_magic_numbers
# ---------------------------------------------------------------------------

@register_fix("no_magic_numbers", confidence=0.75, category="review")
def fix_no_magic_numbers(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Suggest extracting a bare magic number to a named constant."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match a comparison or assignment containing a bare integer (not 0 or 1)
    pattern = re.compile(r"[><=!]+\s*(\d+)")
    m = pattern.search(line)
    if not m:
        return None

    number = m.group(1)
    # Skip trivial constants 0 and 1
    if number in ("0", "1"):
        return None

    indent = re.match(r"^(\s*)", line).group(1)
    const_name = f"THRESHOLD_{number}"
    const_line = f"{const_name} = {number}  # TODO: give a meaningful name\n"
    new_line = line.replace(number, const_name, 1)
    if not new_line.endswith("\n"):
        new_line += "\n"

    replacement = const_line + new_line

    return FixPatch(
        rule_id="no_magic_numbers",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            f"The magic number {number} should be extracted to a named "
            "constant so its intent is clear and it can be changed in one place."
        ),
        confidence=0.75,
        category="review",
    )


# ---------------------------------------------------------------------------
# 5. missing_error_type
# ---------------------------------------------------------------------------

@register_fix("missing_error_type", confidence=0.7, category="review")
def fix_missing_error_type(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``raise Exception(...)`` with ``raise ValueError(...)``."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    pattern = re.compile(r"raise\s+Exception\(")
    if not pattern.search(line):
        return None

    new_line = re.sub(r"raise\s+Exception\(", "raise ValueError(", line)
    if not new_line.endswith("\n"):
        new_line += "\n"

    return FixPatch(
        rule_id="missing_error_type",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            "Using the generic ``Exception`` hides the error's nature. "
            "``ValueError`` is more appropriate for input validation errors "
            "and makes callers' except-clauses more precise."
        ),
        confidence=0.7,
        category="review",
    )


# ---------------------------------------------------------------------------
# 6. global_variable
# ---------------------------------------------------------------------------

@register_fix("global_variable", confidence=0.7, category="review")
def fix_global_variable(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Suggest UPPER_SNAKE naming for mutable module-level variables."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match unindented mutable assignment: name = [] or name = {} or name = set()
    pattern = re.compile(r"^([a-z_]\w*)\s*=\s*(\[\]|\{\}|set\(\))")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    var_name = m.group(1)
    upper_name = var_name.upper()

    new_line = line.replace(var_name, upper_name, 1)
    if not new_line.endswith("\n"):
        new_line += "\n"

    return FixPatch(
        rule_id="global_variable",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            f"Module-level mutable variable ``{var_name}`` should use "
            f"UPPER_SNAKE_CASE (``{upper_name}``) to signal it is a "
            "module-level constant/global per PEP 8 conventions."
        ),
        confidence=0.7,
        category="review",
    )


# ---------------------------------------------------------------------------
# 7. hardcoded_model
# ---------------------------------------------------------------------------

@register_fix("hardcoded_model", confidence=0.7, category="review")
def fix_hardcoded_model(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Suggest extracting hardcoded AI model names to a constant."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match quoted model name strings
    pattern = re.compile(
        r"""(["'])(gpt-4(?:o|-turbo)?|gpt-3\.5-turbo|claude[-\w]*)(["'])"""
    )
    m = pattern.search(line)
    if not m:
        return None

    model_name = m.group(2)
    quote = m.group(1)
    const_name = "MODEL_NAME"

    indent = re.match(r"^(\s*)", line).group(1)
    const_line = f"{const_name} = {quote}{model_name}{quote}  # TODO: move to config\n"
    new_line = line[:m.start()] + const_name + line[m.end():]
    if not new_line.endswith("\n"):
        new_line += "\n"

    replacement = const_line + new_line

    return FixPatch(
        rule_id="hardcoded_model",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            f"The model name ``{model_name}`` is hardcoded. Extract it to a "
            "constant or configuration variable so model changes require "
            "editing only one place."
        ),
        confidence=0.7,
        category="review",
    )


# ---------------------------------------------------------------------------
# 8. missing_response_model
# ---------------------------------------------------------------------------

@register_fix("missing_response_model", confidence=0.6, category="review")
def fix_missing_response_model(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``response_model=dict`` to FastAPI route decorators missing it."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match @app.get("/path") or @app.post("/path") without response_model
    pattern = re.compile(
        r"""(@\w+\.(get|post|put|patch|delete)\s*\(\s*(["'][^"']+["']))(\s*\))"""
    )
    m = pattern.search(line)
    if not m:
        return None

    # Ensure response_model is not already present
    if "response_model" in line:
        return None

    new_line = line[:m.start(4)] + ", response_model=dict" + line[m.start(4):]
    if not new_line.endswith("\n"):
        new_line += "\n"

    return FixPatch(
        rule_id="missing_response_model",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=new_line,
        explanation=(
            "FastAPI endpoints should declare a ``response_model`` for "
            "automatic validation, serialization, and OpenAPI schema "
            "generation. Adding ``response_model=dict`` as a placeholder."
        ),
        confidence=0.6,
        category="review",
    )
