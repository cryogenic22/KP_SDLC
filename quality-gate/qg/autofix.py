"""Auto-Fix Diff Engine.

Generates machine-applicable unified diffs for findings.
The "silent teaching" approach -- developers learn patterns
through corrections, not documentation.
"""

from __future__ import annotations

import difflib
import re
import textwrap
from dataclasses import dataclass


@dataclass
class AutoFix:
    rule: str
    file: str
    line: int
    original: str       # Original code lines
    fixed: str          # Fixed code lines
    diff: str           # Unified diff format
    confidence: str     # "high", "medium", "low"


def _make_diff(original_lines: list[str], fixed_lines: list[str], filename: str) -> str:
    """Produce a unified diff string from two lists of lines."""
    # Ensure lines end with newline for proper diff output
    orig = [l + "\n" for l in original_lines]
    fixed = [l + "\n" for l in fixed_lines]
    diff_lines = list(difflib.unified_diff(
        orig, fixed,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))
    return "".join(diff_lines)


def _fix_no_silent_catch(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Fix bare except: pass and except Exception: pass patterns."""
    # Search for the except/pass pattern in the provided lines
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        # Match 'except:' or 'except Exception:'
        if stripped in ("except:", "except Exception:"):
            # Check if the next line is 'pass'
            if i + 1 < len(lines) and lines[i + 1].strip() == "pass":
                # Determine indentation from the except line
                indent = len(raw_line) - len(raw_line.lstrip())
                indent_str = raw_line[:indent] if indent else ""
                body_indent = lines[i + 1][:len(lines[i + 1]) - len(lines[i + 1].lstrip())]

                original_snippet = lines[i] + "\n" + lines[i + 1]

                new_except = f"{indent_str}except Exception as e:"
                new_body = f"{body_indent}logger.warning(f\"Suppressed: {{e}}\")"

                fixed_snippet = new_except + "\n" + new_body

                diff = _make_diff(
                    [lines[i], lines[i + 1]],
                    [new_except, new_body],
                    file,
                )

                return AutoFix(
                    rule="no_silent_catch",
                    file=file,
                    line=context_start + i + 1,
                    original=original_snippet,
                    fixed=fixed_snippet,
                    diff=diff,
                    confidence="high",
                )
    return None


def _fix_missing_requests_timeout(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Add timeout=30 to requests.get/post/put/patch/delete calls."""
    # Pattern: requests.<method>(...) without timeout
    pattern = re.compile(r'(requests\.(?:get|post|put|patch|delete|head|options)\()(.*)\)')

    for i, raw_line in enumerate(lines):
        match = pattern.search(raw_line)
        if match and "timeout" not in raw_line:
            prefix = match.group(1)
            args = match.group(2)

            # Build the fixed line: insert timeout=30 before closing paren
            if args.strip():
                new_call = f"{prefix}{args}, timeout=30)"
            else:
                new_call = f"{prefix}timeout=30)"

            # Reconstruct the full line by replacing the matched portion
            fixed_line = raw_line[:match.start()] + new_call + raw_line[match.end():]

            original_snippet = raw_line
            fixed_snippet = fixed_line

            diff = _make_diff(
                [raw_line],
                [fixed_line],
                file,
            )

            return AutoFix(
                rule="missing_requests_timeout",
                file=file,
                line=context_start + i + 1,
                original=original_snippet,
                fixed=fixed_snippet,
                diff=diff,
                confidence="high",
            )
    return None


def _fix_bare_except(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Fix bare ``except:`` → ``except Exception:``."""
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if stripped == "except:":
            fixed_line = raw_line.replace("except:", "except Exception:")
            diff = _make_diff([raw_line], [fixed_line], file)
            return AutoFix(
                rule="bare_except",
                file=file,
                line=context_start + i + 1,
                original=raw_line,
                fixed=fixed_line,
                diff=diff,
                confidence="high",
            )
    return None


def _fix_no_debug_statements(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Remove debug statements: breakpoint(), print("DEBUG…), print(">>>…)."""
    debug_print_re = re.compile(
        r'''^\s*print\(\s*(?:f?["'](?:DEBUG|>>>))'''
    )
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        is_debug = False
        if stripped.startswith("breakpoint("):
            is_debug = True
        elif debug_print_re.match(raw_line):
            is_debug = True

        if is_debug:
            diff = _make_diff([raw_line], [], file)
            return AutoFix(
                rule="no_debug_statements",
                file=file,
                line=context_start + i + 1,
                original=raw_line,
                fixed="",
                diff=diff,
                confidence="high",
            )
    return None


def _fix_mutable_default(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    r"""Fix mutable default arguments: ``def f(x=[])`` → ``def f(x=None)`` + guard."""
    # Match function defs with =[] or ={} as a default value
    pattern = re.compile(r'^(\s*def\s+\w+\(.*?)(\w+)\s*=\s*(\[\]|\{\})(.*\):)')

    for i, raw_line in enumerate(lines):
        m = pattern.match(raw_line)
        if m:
            prefix = m.group(1)      # "    def f(" or "def f(other, "
            param = m.group(2)        # "x"
            default = m.group(3)      # "[]" or "{}"
            suffix = m.group(4)       # "):"

            # Build the fixed def line
            fixed_def = f"{prefix}{param}=None{suffix}"

            # Determine body indentation from the next non-empty line, or
            # fall back to def indentation + 4 spaces
            def_indent = len(raw_line) - len(raw_line.lstrip())
            body_indent = " " * (def_indent + 4)
            if i + 1 < len(lines) and lines[i + 1].strip():
                body_indent = lines[i + 1][: len(lines[i + 1]) - len(lines[i + 1].lstrip())]

            guard_line1 = f"{body_indent}if {param} is None:"
            guard_line2 = f"{body_indent}    {param} = {default}"

            original_lines = [raw_line]
            fixed_lines = [fixed_def, guard_line1, guard_line2]

            diff = _make_diff(original_lines, fixed_lines, file)
            return AutoFix(
                rule="mutable_default",
                file=file,
                line=context_start + i + 1,
                original=raw_line,
                fixed="\n".join(fixed_lines),
                diff=diff,
                confidence="high",
            )
    return None


def _fix_regex_compile_in_loop(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Hoist ``re.compile(...)`` out of a for/while loop body."""
    loop_re = re.compile(r'^(\s*)(?:for|while)\s+')
    compile_re = re.compile(r'(\s*)((\w+)\s*=\s*re\.compile\(.+\))')

    for i, raw_line in enumerate(lines):
        loop_m = loop_re.match(raw_line)
        if loop_m:
            loop_indent = loop_m.group(1)
            # Scan the body lines that follow the loop header
            for j in range(i + 1, len(lines)):
                body_line = lines[j]
                # Stop when we leave the loop body (less or equal indent and non-empty)
                if body_line.strip() and not body_line.startswith(loop_indent + " ") and not body_line.startswith(loop_indent + "\t"):
                    break
                cm = compile_re.match(body_line)
                if cm:
                    var_name = cm.group(3)
                    # Build original snippet (loop header + compile line)
                    original_block = [lines[i], body_line]
                    # Build fixed snippet: compile hoisted above loop at loop indent
                    hoisted_line = f"{loop_indent}{cm.group(2).strip()}"
                    fixed_block = [hoisted_line, lines[i]]

                    diff = _make_diff(original_block, fixed_block, file)
                    return AutoFix(
                        rule="regex_compile_in_loop",
                        file=file,
                        line=context_start + i + 1,
                        original="\n".join(original_block),
                        fixed="\n".join(fixed_block),
                        diff=diff,
                        confidence="medium",
                    )
    return None


def _fix_string_concat_in_loop(
    *, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Convert ``result += expr`` inside a loop to list-append + join."""
    loop_re = re.compile(r'^(\s*)(?:for|while)\s+')
    # Match: result += expr  OR  result = result + expr
    concat_plus_eq = re.compile(r'^(\s+)(\w+)\s*\+=\s*(.+)$')
    concat_reassign = re.compile(r'^(\s+)(\w+)\s*=\s*\2\s*\+\s*(.+)$')

    for i, raw_line in enumerate(lines):
        loop_m = loop_re.match(raw_line)
        if loop_m:
            loop_indent = loop_m.group(1)
            for j in range(i + 1, len(lines)):
                body_line = lines[j]
                if body_line.strip() and not body_line.startswith(loop_indent + " ") and not body_line.startswith(loop_indent + "\t"):
                    break
                cm = concat_plus_eq.match(body_line) or concat_reassign.match(body_line)
                if cm:
                    body_indent = cm.group(1)
                    var_name = cm.group(2)
                    expr = cm.group(3).strip()

                    original_block = [lines[i], body_line]

                    init_line = f"{loop_indent}_parts = []"
                    append_line = f"{body_indent}_parts.append({expr})"
                    join_line = f"{loop_indent}{var_name} = \"\".join(_parts)"

                    fixed_block = [init_line, lines[i], append_line, join_line]

                    diff = _make_diff(original_block, fixed_block, file)
                    return AutoFix(
                        rule="string_concat_in_loop",
                        file=file,
                        line=context_start + i + 1,
                        original="\n".join(original_block),
                        fixed="\n".join(fixed_block),
                        diff=diff,
                        confidence="medium",
                    )
    return None


# Registry of fixers by rule name
_FIXERS = {
    "no_silent_catch": _fix_no_silent_catch,
    "missing_requests_timeout": _fix_missing_requests_timeout,
    "bare_except": _fix_bare_except,
    "no_debug_statements": _fix_no_debug_statements,
    "mutable_default": _fix_mutable_default,
    "regex_compile_in_loop": _fix_regex_compile_in_loop,
    "string_concat_in_loop": _fix_string_concat_in_loop,
}


def generate_fix(
    *, rule: str, file: str, line: int, lines: list[str], context_start: int
) -> AutoFix | None:
    """Generate an auto-fix for a finding. Returns None if no fix available."""
    fixer = _FIXERS.get(rule)
    if fixer is None:
        return None

    # Never mutate the input list -- work on a copy
    lines_copy = list(lines)
    return fixer(file=file, line=line, lines=lines_copy, context_start=context_start)
