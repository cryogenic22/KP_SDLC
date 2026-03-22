"""Auto-Fix Diff Engine.

Generates machine-applicable unified diffs for findings.
The "silent teaching" approach -- developers learn patterns
through corrections, not documentation.
"""

from __future__ import annotations

import difflib
import re
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


# Registry of fixers by rule name
_FIXERS = {
    "no_silent_catch": _fix_no_silent_catch,
    "missing_requests_timeout": _fix_missing_requests_timeout,
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
