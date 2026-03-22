"""
Prompt Quality Gate rule pack (PROMPT-PY-*).

In agentic projects, prompts are the new business logic. These rules
enforce prompt hygiene: versioning, separation, structured output, injection.

Rules:
  PROMPT-PY-NO-VERSION        – Prompt string without version metadata
  PROMPT-PY-CONCAT-SYSTEM-USER – System + user prompt concatenated unsafely
  PROMPT-PY-NO-STRUCTURED-OUTPUT – LLM call expects JSON but has no response_format
  PROMPT-PY-INJECTION-VECTOR  – Unsanitized user input interpolated into prompt
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable


def check_prompt_quality(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    add_issue: Callable,
) -> None:
    """Run all PROMPT-PY-* checks on a single file."""

    # Early exit: only check files that look prompt-related
    if not _is_prompt_file(content):
        return

    _check_no_version(lines=lines, content=content, add_issue=add_issue)
    _check_concat_system_user(lines=lines, content=content, add_issue=add_issue)
    _check_no_structured_output(lines=lines, content=content, add_issue=add_issue)
    _check_injection_vector(lines=lines, content=content, add_issue=add_issue)


# ── Heuristic: is this file prompt-related? ─────────────────────────────

_PROMPT_SIGNALS = re.compile(
    r"""
      _[Pp][Rr][Oo][Mm][Pp][Tt]\b   # *_PROMPT or *_prompt variable
    | \bsystem_prompt\b
    | \buser_input\b
    | \buser_query\b
    | \bprompt\s*=\s*f?["']{1,3}
    | \bchat\.completions\.create\b
    | \bllm\.invoke\b
    | \bmessages\s*=\s*\[
    """,
    re.VERBOSE,
)


def _is_prompt_file(content: str) -> bool:
    return bool(_PROMPT_SIGNALS.search(content))


# ── PROMPT-PY-NO-VERSION ────────────────────────────────────────────────

# Matches lines like:  SYSTEM_PROMPT = """..."""  or  AGENT_PROMPT = "..."
_PROMPT_VAR_RE = re.compile(
    r'^(\s*[A-Za-z_][A-Za-z0-9_]*_[Pp][Rr][Oo][Mm][Pp][Tt])\s*=\s*',
)

# Version signals that indicate the prompt is versioned
_VERSION_RE = re.compile(
    r'prompt_version\s*[:=]|PROMPT_VERSION\s*=',
    re.IGNORECASE,
)


def _check_no_version(
    *, lines: list[str], content: str, add_issue: Callable,
) -> None:
    # If the file has a global version marker, all prompts are considered versioned
    if _VERSION_RE.search(content):
        return

    for i, line in enumerate(lines, start=1):
        if _PROMPT_VAR_RE.match(line):
            # Check a window of 5 lines above for a version comment/variable
            start = max(0, i - 6)  # i is 1-based; lines is 0-based
            window = "\n".join(lines[start : i - 1])
            if _VERSION_RE.search(window):
                continue
            add_issue(
                line=i,
                rule="PROMPT-PY-NO-VERSION",
                severity="warning",
                message="Prompt variable has no version metadata (comment or PROMPT_VERSION).",
                suggestion=(
                    "Add a '# prompt_version: X.Y' comment above the prompt "
                    "or a PROMPT_VERSION variable nearby."
                ),
            )


# ── PROMPT-PY-CONCAT-SYSTEM-USER ────────────────────────────────────────

# Pattern 1: string concat with +   e.g.  system_prompt + user_input
_CONCAT_PLUS_RE = re.compile(
    r'system_prompt\s*\+\s*(?:user_input|user_query)'
    r'|(?:user_input|user_query)\s*\+\s*system_prompt',
)

# Pattern 2: f-string mixing both  e.g.  f"{system_prompt}\n{user_input}"
_CONCAT_FSTRING_RE = re.compile(
    r'f["\'].*\{system_prompt\}.*\{(?:user_input|user_query)\}'
    r'|f["\'].*\{(?:user_input|user_query)\}.*\{system_prompt\}',
)


def _check_concat_system_user(
    *, lines: list[str], content: str, add_issue: Callable,
) -> None:
    for i, line in enumerate(lines, start=1):
        if _CONCAT_PLUS_RE.search(line) or _CONCAT_FSTRING_RE.search(line):
            add_issue(
                line=i,
                rule="PROMPT-PY-CONCAT-SYSTEM-USER",
                severity="warning",
                message="System prompt and user input are concatenated directly.",
                suggestion=(
                    "Use messages=[{role:'system', content: ...}, "
                    "{role:'user', content: ...}] to separate roles."
                ),
            )


# ── PROMPT-PY-NO-STRUCTURED-OUTPUT ──────────────────────────────────────

_JSON_IN_STRING_RE = re.compile(
    r"""['"][^'"]*\bjson\b[^'"]*['"]""",
    re.IGNORECASE,
)

_LLM_CALL_RE = re.compile(
    r'\b(?:completions\.create|chat\.create|llm\.invoke|generate)\s*\(',
)


def _check_no_structured_output(
    *, lines: list[str], content: str, add_issue: Callable,
) -> None:
    # Strategy: detect if file mentions JSON in a string AND has an LLM call
    # without response_format.
    has_json_string = False
    json_line = 0

    for i, line in enumerate(lines, start=1):
        if _JSON_IN_STRING_RE.search(line):
            has_json_string = True
            if json_line == 0:
                json_line = i

    if not has_json_string:
        return

    # Check if there is a response_format anywhere in the content
    if re.search(r'\bresponse_format\s*=', content):
        return

    # Find the LLM call line to attach the issue to
    for i, line in enumerate(lines, start=1):
        if _LLM_CALL_RE.search(line):
            add_issue(
                line=i,
                rule="PROMPT-PY-NO-STRUCTURED-OUTPUT",
                severity="warning",
                message=(
                    "Prompt expects JSON output but LLM call has no response_format parameter."
                ),
                suggestion=(
                    "Add response_format={'type': 'json_object'} to the LLM call."
                ),
            )
            return

    # If no explicit LLM call line found, flag the JSON string line
    add_issue(
        line=json_line,
        rule="PROMPT-PY-NO-STRUCTURED-OUTPUT",
        severity="warning",
        message="Prompt expects JSON output but no response_format found in file.",
        suggestion="Add response_format={'type': 'json_object'} to the LLM call.",
    )


# ── PROMPT-PY-INJECTION-VECTOR ──────────────────────────────────────────

# f-string prompt containing user_input or user_query directly
_FSTRING_USER_RE = re.compile(
    r'f["\'].*\{(user_input|user_query)\}',
)

# Check whether the variable has been sanitized before use.
# We look for patterns like:  sanitize(user_input)  or  sanitize_input(user_input)
_SANITIZE_RE = re.compile(
    r'\bsanitize\w*\s*\(\s*(?:user_input|user_query)\s*\)',
)


def _check_injection_vector(
    *, lines: list[str], content: str, add_issue: Callable,
) -> None:
    # If the file contains a sanitize call for user input, consider it safe
    if _SANITIZE_RE.search(content):
        return

    for i, line in enumerate(lines, start=1):
        m = _FSTRING_USER_RE.search(line)
        if m:
            var_name = m.group(1)
            add_issue(
                line=i,
                rule="PROMPT-PY-INJECTION-VECTOR",
                severity="error",
                message=(
                    f"Unsanitized '{var_name}' interpolated directly into f-string prompt."
                ),
                suggestion=(
                    f"Pass {var_name} through a sanitize function before interpolation, "
                    f"e.g. sanitize_input({var_name})."
                ),
            )
