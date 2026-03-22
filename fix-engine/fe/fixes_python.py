"""Python-specific fix functions.

Six fixers targeting common Python anti-patterns that go beyond simple style.
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


def _get_lines(file_content: str) -> list[str]:
    """Return all lines preserving line endings."""
    return file_content.splitlines(keepends=True)


# ---------------------------------------------------------------------------
# 1. missing_encoding
# ---------------------------------------------------------------------------

@register_fix("missing_encoding", confidence=0.95, category="safe")
def fix_missing_encoding(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``encoding='utf-8'`` to ``open()`` calls that lack it."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match open(...) that does NOT already contain 'encoding'
    if "encoding" in line:
        return None

    # Insert encoding='utf-8' before the closing paren
    pattern = re.compile(r"(open\s*\([^)]*?)(\)\s*)$")
    m = pattern.search(line.rstrip("\n"))
    if not m:
        return None

    before_close = m.group(1)
    close_and_after = m.group(2)
    # Add comma if there are existing args
    separator = ", " if before_close.rstrip().endswith(("'", '"', ")")) or re.search(r'["\'\w]\s*$', before_close) else ", "
    replacement_line = line[:m.start()] + before_close + separator + "encoding='utf-8'" + close_and_after + "\n"

    return FixPatch(
        rule_id="missing_encoding",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement_line,
        explanation=(
            "Without an explicit ``encoding`` argument, ``open()`` uses "
            "the platform default encoding which varies across OSes. "
            "Specifying ``encoding='utf-8'`` makes behaviour portable."
        ),
        confidence=0.95,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 2. no_silent_catch
# ---------------------------------------------------------------------------

@register_fix("no_silent_catch", confidence=0.9, category="safe")
def fix_no_silent_catch(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Replace ``except: pass`` with proper exception logging."""
    line_no = finding.get("line", 0)
    lines = _get_lines(file_content)

    # The finding line should point to the except line
    if line_no < 1 or line_no > len(lines):
        return None

    except_line = lines[line_no - 1]
    # Verify this is an except line
    except_match = re.match(r"^(\s*)except\s*:\s*$", except_line.rstrip("\n"))
    if not except_match:
        # Also match "except:" with pass on the next line
        except_match = re.match(r"^(\s*)except\s*:\s*$", except_line.rstrip("\n"))
        if not except_match:
            return None

    indent = except_match.group(1)
    body_indent = indent + "    "

    # Check if the next line is "pass"
    pass_line = ""
    if line_no < len(lines):
        next_line = lines[line_no]
        if next_line.strip() == "pass":
            pass_line = next_line

    # Build original block (except: + pass)
    original = except_line
    if pass_line:
        original += pass_line

    replacement = (
        f"{indent}except Exception as e:\n"
        f"{body_indent}logger.warning(\"Caught exception: %s\", e)\n"
    )

    return FixPatch(
        rule_id="no_silent_catch",
        file_path=finding.get("file", ""),
        line=line_no,
        original=original,
        replacement=replacement,
        explanation=(
            "Silently swallowing exceptions (``except: pass``) hides bugs. "
            "Log the exception so failures are visible."
        ),
        confidence=0.9,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 3. regex_compile_in_loop
# ---------------------------------------------------------------------------

@register_fix("regex_compile_in_loop", confidence=0.9, category="review")
def fix_regex_compile_in_loop(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Hoist ``re.compile(...)`` above the enclosing loop."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match: <var> = re.compile(...)
    pattern = re.compile(r"^(\s*)(\w+)\s*=\s*(re\.compile\(.+\))\s*$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    var_name = m.group(2)
    compile_call = m.group(3)

    # Find the loop line above
    lines = _get_lines(file_content)
    loop_line_no = None
    for i in range(line_no - 2, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("for ") or stripped.startswith("while "):
            loop_line_no = i + 1  # 1-based
            break

    if loop_line_no is None:
        return None

    loop_line = lines[loop_line_no - 1]
    loop_indent = re.match(r"^(\s*)", loop_line).group(1)

    # The compile should be placed just before the loop, at the loop's indent
    hoisted = f"{loop_indent}{var_name} = {compile_call}\n"
    replacement = hoisted + loop_line

    return FixPatch(
        rule_id="regex_compile_in_loop",
        file_path=finding.get("file", ""),
        line=loop_line_no,
        original=loop_line,
        replacement=replacement,
        explanation=(
            "``re.compile()`` inside a loop recompiles the regex every "
            "iteration. Hoist it above the loop for better performance."
        ),
        confidence=0.9,
        category="review",
    )


# ---------------------------------------------------------------------------
# 4. string_concat_in_loop
# ---------------------------------------------------------------------------

@register_fix("string_concat_in_loop", confidence=0.85, category="review")
def fix_string_concat_in_loop(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Convert ``s += expr`` inside a loop to list append + join."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    pattern = re.compile(r"^(\s*)(\w+)\s*\+=\s*(.+)$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    var_name = m.group(2)
    expr = m.group(3)

    replacement = f"{indent}__{var_name}_parts.append({expr})\n"
    return FixPatch(
        rule_id="string_concat_in_loop",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "String concatenation with ``+=`` inside a loop is O(n^2). "
            "Collect parts in a list and ``''.join()`` after the loop."
        ),
        confidence=0.85,
        category="review",
    )


# ---------------------------------------------------------------------------
# 5. missing_requests_timeout
# ---------------------------------------------------------------------------

@register_fix("missing_requests_timeout", confidence=0.95, category="safe")
def fix_missing_requests_timeout(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Add ``timeout=30`` to requests.get/post/put/delete/patch calls."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    if "timeout" in line:
        return None

    # Match requests.<method>(...) without timeout
    pattern = re.compile(
        r"(requests\.(?:get|post|put|delete|patch|head|options)\s*\([^)]*?)(\)\s*)$"
    )
    m = pattern.search(line.rstrip("\n"))
    if not m:
        return None

    before_close = m.group(1)
    close = m.group(2)
    replacement_line = line[:m.start()] + before_close + ", timeout=30" + close + "\n"

    return FixPatch(
        rule_id="missing_requests_timeout",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement_line,
        explanation=(
            "HTTP requests without a timeout can hang indefinitely. "
            "Adding ``timeout=30`` prevents resource exhaustion."
        ),
        confidence=0.95,
        category="safe",
    )


# ---------------------------------------------------------------------------
# 6. return_in_init
# ---------------------------------------------------------------------------

@register_fix("return_in_init", confidence=0.95, category="safe")
def fix_return_in_init(
    finding: Dict, file_content: str, config: Dict
) -> Optional[FixPatch]:
    """Remove ``return <value>`` from ``__init__`` (only bare return allowed)."""
    line_no = finding.get("line", 0)
    line = _get_line(file_content, line_no)
    if line is None:
        return None

    # Match "return <something>" but not bare "return"
    pattern = re.compile(r"^(\s*)return\s+(.+)$")
    m = pattern.match(line.rstrip("\n"))
    if not m:
        return None

    indent = m.group(1)
    replacement = f"{indent}return\n"
    return FixPatch(
        rule_id="return_in_init",
        file_path=finding.get("file", ""),
        line=line_no,
        original=line,
        replacement=replacement,
        explanation=(
            "``__init__`` must not return a value. Returning a non-None "
            "value raises TypeError at runtime. Use a bare ``return``."
        ),
        confidence=0.95,
        category="safe",
    )
