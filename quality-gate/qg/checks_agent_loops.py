"""FEAT-007 — Agent-Loop-Safety Rule Pack.

Detects unbounded agent loops that work in testing but fail
expensively in production (adversarial or unexpected inputs
trigger infinite loops with compounding API costs).

Rules:
- LOOP-PY-WHILE-TRUE-LLM: while True + LLM call without break/return
- LOOP-PY-NO-MAX-ITERATIONS: loop + LLM call without iteration bound
- LOOP-PY-LANGGRAPH-UNBOUNDED: StateGraph without recursion_limit
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List


# Patterns that indicate an LLM call — require known LLM object prefixes
# to avoid matching local functions like generate_html(), task.complete(), etc.
_LLM_CALL = re.compile(
    r"\b(?:(?:llm|model|client|chain|agent|openai|anthropic|bedrock|"
    r"chat|completion_api|langchain|crew|llm_service|llm_client|"
    r"llm_chain|ai_client|genai|graph|workflow|pipeline)\."
    r"(?:invoke|generate|predict|complete|ainvoke|agenerate|run|create|"
    r"get_text_response|get_text_response_async|get_response|call|acall)|"
    r"completions?\.create|ChatCompletion\.create|"
    r"llm\(|chain\()"
)

# Patterns indicating iteration bounds
_BOUND_PATTERNS = re.compile(
    r"(?:MAX_ITER|max_iter|max_retries|MAX_RETRIES|max_attempts|"
    r"MAX_ATTEMPTS|limit|LIMIT|\[:[\w.]+\]|range\(\w+\)|"
    r"enumerate\([^)]*\[:)"
)


def check_agent_loop_safety(
    *,
    file_path: Path,
    content: str,
    lines: List[str],
    add_issue: Callable,
) -> None:
    """Run all Agent-Loop-Safety checks on a file."""
    _check_while_true_llm(lines=lines, add_issue=add_issue)
    _check_no_max_iterations(lines=lines, add_issue=add_issue)
    _check_langgraph_unbounded(lines=lines, content=content, add_issue=add_issue)


def _check_while_true_llm(*, lines: List[str], add_issue: Callable) -> None:
    """LOOP-PY-WHILE-TRUE-LLM: while True + LLM call without break."""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped != "while True:":
            i += 1
            continue

        # Found while True — scan body for LLM call and break/return
        while_indent = len(lines[i]) - len(lines[i].lstrip())
        has_llm_call = False
        has_break = False
        body_start = i + 1
        j = body_start

        while j < len(lines) and j < i + 30:  # scan up to 30 lines
            line = lines[j]
            line_stripped = line.strip()

            # Check if we've left the while body
            if line_stripped and not line_stripped.startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= while_indent:
                    break

            if _LLM_CALL.search(line):
                has_llm_call = True
            if line_stripped.startswith(("break", "return")):
                has_break = True

            j += 1

        if has_llm_call and not has_break:
            add_issue(
                line=i + 1,
                rule="LOOP-PY-WHILE-TRUE-LLM",
                severity="critical",
                message="while True loop with LLM call and no break/return. This is an unbounded cost loop.",
                suggestion="Add explicit termination: break on success condition, max iteration counter, or timeout.",
            )

        i = j


def _check_no_max_iterations(*, lines: List[str], add_issue: Callable) -> None:
    """LOOP-PY-NO-MAX-ITERATIONS: loop + LLM call without iteration bound."""
    loop_pattern = re.compile(r"^\s*for\s+\w+\s+in\s+")

    i = 0
    while i < len(lines):
        match = loop_pattern.match(lines[i])
        if not match:
            i += 1
            continue

        loop_line = lines[i]
        loop_indent = len(loop_line) - len(loop_line.lstrip())

        # Check if the iterable has a bound ([:N], range(N), etc.)
        has_bound = bool(_BOUND_PATTERNS.search(loop_line))

        # Scan body for LLM call
        has_llm_call = False
        j = i + 1
        while j < len(lines) and j < i + 20:
            line = lines[j]
            line_stripped = line.strip()

            if line_stripped and not line_stripped.startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= loop_indent:
                    break

            if _LLM_CALL.search(line):
                has_llm_call = True

            j += 1

        if has_llm_call and not has_bound:
            add_issue(
                line=i + 1,
                rule="LOOP-PY-NO-MAX-ITERATIONS",
                severity="error",
                message="Loop with LLM call has no iteration bound. Unbounded input can cause runaway API costs.",
                suggestion="Add a maximum: `for item in items[:MAX_BATCH]` or use `itertools.islice(items, MAX_BATCH)`.",
            )

        i = j if j > i + 1 else i + 1


def _check_langgraph_unbounded(*, lines: List[str], content: str, add_issue: Callable) -> None:
    """LOOP-PY-LANGGRAPH-UNBOUNDED: StateGraph without recursion_limit."""
    if "StateGraph" not in content:
        return

    has_stategraph = False
    stategraph_line = 0
    has_recursion_limit = "recursion_limit" in content

    for i, line in enumerate(lines):
        if "StateGraph(" in line:
            has_stategraph = True
            stategraph_line = i + 1

    if has_stategraph and not has_recursion_limit:
        add_issue(
            line=stategraph_line,
            rule="LOOP-PY-LANGGRAPH-UNBOUNDED",
            severity="error",
            message="LangGraph StateGraph without recursion_limit. Agent can loop indefinitely.",
            suggestion="Add recursion_limit to compile(): `graph.compile(recursion_limit=25)`",
        )
