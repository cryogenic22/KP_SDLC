"""FEAT-005 — LLM-Output-Safety Rule Pack.

Detects unvalidated LLM output usage patterns that cause silent failures
in production agentic applications.

Detection approach: identify lines that call LLM functions (completions.create,
chain.invoke, llm.generate, etc.) and track the response variable. Then check
if subsequent usage of that variable has proper validation.

Rules:
- LLM-PY-UNVALIDATED-JSON: json.loads on LLM response without try/except
- LLM-PY-DIRECT-EVAL: eval() on any LLM-derived value (CRITICAL)
- LLM-PY-DICT-ACCESS-NO-GUARD: response["key"] without .get() or KeyError
- LLM-PY-SILENT-FALLBACK: `or {}` / `or []` on LLM output
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List


# Two-tier LLM detection:
# Tier 1: Explicit LLM API calls (known object prefixes)
_LLM_OBJ = (
    r"(?:llm|model|client|chain|agent|openai|anthropic|bedrock|"
    r"chat|completion_api|langchain|crew|llm_service|llm_client|"
    r"llm_chain|llm_model|ai_client|genai|graph|workflow|pipeline)"
)
_LLM_CALL_PATTERNS = re.compile(
    rf"\b(?:completions?\.create|chat\.completions|"
    rf"{_LLM_OBJ}\.(?:invoke|generate|predict|complete|run|ainvoke|"
    rf"agenerate|create|get_text_response|get_response|call|acall|"
    rf"get_text_response_async)|"
    r"llm\(|chain\()"
)

# Tier 2: Variable names that strongly suggest LLM output.
# Used to detect json.loads(llm_response) even when the LLM call
# is in a different function / service layer (common in enterprise code).
_LLM_VAR_NAMES = re.compile(
    r"\b(?:llm_response|llm_output|llm_result|ai_response|"
    r"completion_result|model_response|model_output|"
    r"generated_text|generation_result)\b"
)

# Patterns for variable assignment from LLM
_LLM_ASSIGN = re.compile(
    rf"^\s*(\w+)\s*=\s*.*(?:completions?\.create|"
    rf"{_LLM_OBJ}\.(?:invoke|ainvoke|generate|predict|complete|run|create|"
    rf"get_text_response|get_text_response_async|get_response)|"
    r"llm\(|chain\()"
)


def check_llm_output_safety(
    *,
    file_path: Path,
    content: str,
    lines: List[str],
    add_issue: Callable,
) -> None:
    """Run all LLM-Output-Safety checks on a file."""
    has_llm_calls = _LLM_CALL_PATTERNS.search(content)
    has_llm_vars = _LLM_VAR_NAMES.search(content)
    if not has_llm_calls and not has_llm_vars:
        return  # No LLM calls or LLM variables in this file — skip

    _check_unvalidated_json(lines=lines, add_issue=add_issue)
    _check_direct_eval(lines=lines, content=content, add_issue=add_issue)
    _check_silent_fallback(lines=lines, content=content, add_issue=add_issue)
    _check_dict_access_no_guard(lines=lines, content=content, add_issue=add_issue)


def _check_unvalidated_json(*, lines: List[str], add_issue: Callable) -> None:
    """LLM-PY-UNVALIDATED-JSON: json.loads on LLM response without try/except."""
    # Find json.loads calls and check if they're inside a try block
    in_try_block = False
    try_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track try blocks
        if stripped.startswith("try:"):
            in_try_block = True
            try_indent = len(line) - len(line.lstrip())
        elif in_try_block and stripped.startswith(("except", "finally")):
            if (len(line) - len(line.lstrip())) <= try_indent:
                in_try_block = False

        # Check for json.loads on LLM-related variables
        if "json.loads(" in stripped and not in_try_block:
            # Check if the argument looks LLM-derived
            if any(kw in stripped for kw in [
                "response", "completion", "result", "output", ".content",
                ".message", "choices[", "invoke", "generate",
            ]):
                add_issue(
                    line=i + 1,
                    rule="LLM-PY-UNVALIDATED-JSON",
                    severity="error",
                    message="json.loads() on LLM response without try/except. LLM output is not guaranteed to be valid JSON.",
                    suggestion="Wrap in try/except json.JSONDecodeError and handle the failure case explicitly.",
                )


def _check_direct_eval(*, lines: List[str], content: str, add_issue: Callable) -> None:
    """LLM-PY-DIRECT-EVAL: eval() on LLM-derived value."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "eval(" in stripped:
            # Check surrounding context for LLM calls or LLM variable names
            context_start = max(0, i - 10)
            context = "\n".join(lines[context_start:i + 1])
            if _LLM_CALL_PATTERNS.search(context) or _LLM_VAR_NAMES.search(context):
                add_issue(
                    line=i + 1,
                    rule="LLM-PY-DIRECT-EVAL",
                    severity="critical",
                    message="eval() used near LLM output. This is a code injection vector — LLM output is untrusted input.",
                    suggestion="Never use eval() on LLM output. Parse structured output with json.loads() and Pydantic validation instead.",
                )


def _check_silent_fallback(*, lines: List[str], content: str, add_issue: Callable) -> None:
    """LLM-PY-SILENT-FALLBACK: `or {}` / `or []` on LLM-related variables."""
    # Only check files with LLM calls
    fallback_pattern = re.compile(r"\bor\s+(\{\}|\[\])\s*$")

    for i, line in enumerate(lines):
        match = fallback_pattern.search(line.strip())
        if not match:
            continue

        # Check if this line or nearby lines involve LLM output
        context_start = max(0, i - 5)
        context = "\n".join(lines[context_start:i + 1])
        if _LLM_CALL_PATTERNS.search(context) or _LLM_VAR_NAMES.search(context) or any(
            kw in line for kw in ["response", "result", "output", "invoke"]
        ):
            fallback_val = match.group(1)
            add_issue(
                line=i + 1,
                rule="LLM-PY-SILENT-FALLBACK",
                severity="warning",
                message=f"Silent fallback `or {fallback_val}` on LLM output. Empty result looks like success to downstream code.",
                suggestion="Handle the empty/None case explicitly. Log a warning and return a typed error, not an empty container.",
            )


def _check_dict_access_no_guard(*, lines: List[str], content: str, add_issue: Callable) -> None:
    """LLM-PY-DICT-ACCESS-NO-GUARD: response["key"] without .get()."""
    # Find response variables from LLM calls
    llm_vars = set()
    for i, line in enumerate(lines):
        match = _LLM_ASSIGN.match(line)
        if match:
            llm_vars.add(match.group(1))

    if not llm_vars:
        return

    # Check for direct dict access on LLM variables
    dict_access = re.compile(r'\b(' + '|'.join(re.escape(v) for v in llm_vars) + r')\["[^"]+"\]')

    for i, line in enumerate(lines):
        if dict_access.search(line):
            # Verify it's not inside a try block
            in_try = False
            for j in range(max(0, i - 10), i):
                if lines[j].strip().startswith("try:"):
                    in_try = True
                elif lines[j].strip().startswith(("except", "finally")):
                    in_try = False

            if not in_try:
                add_issue(
                    line=i + 1,
                    rule="LLM-PY-DICT-ACCESS-NO-GUARD",
                    severity="warning",
                    message="Direct dict access on LLM response variable. LLM may not return expected keys.",
                    suggestion="Use .get('key', default) or wrap in try/except KeyError.",
                )
