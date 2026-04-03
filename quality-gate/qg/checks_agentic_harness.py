"""Agentic Harness Policy Pack.

Detects anti-patterns in agentic system harnesses that violate
the Agentic System Design Principles (Section 11 checklist).

Rules:
- AGENT-PY-INLINE-TOOL-DEF:       Tool definitions embedded in prompt strings
- AGENT-PY-PROMPT-ONLY-PERMISSION: Permission enforcement only in prompts
- AGENT-PY-NO-SESSION-PERSISTENCE: Agent loop without checkpoint/persist
- AGENT-PY-STATE-CONFLATION:       Workflow state appended to message lists
- AGENT-PY-NO-BUDGET-CHECK:        LLM call in loop without budget check
- AGENT-PY-UNVERIFIED-HANDOFF:     Direct output passing without verification
- AGENT-PY-UNBOUNDED-HISTORY:      Message list growing without windowing
- AGENT-PY-STATIC-TOOL-POOL:       Same tools used across all loop turns
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, List


# ── Early-exit guard ────────────────────────────────────────────────
_AGENT_MARKERS = re.compile(
    r"invoke|tool_call|agent|workflow|harness|execute_tool|completions?\.create",
    re.IGNORECASE,
)

# ── LLM call patterns ──────────────────────────────────────────────
_LLM_CALL = re.compile(
    r"\b(?:llm|model|client|chain|agent|openai|anthropic|chat|completion)"
    r"[\w.]*\.(?:invoke|generate|predict|complete|create|run|call)"
    r"|completions?\.create"
)


def check_agentic_harness(
    *,
    file_path: Path,
    content: str,
    lines: list[str],
    add_issue: Callable,
) -> None:
    """Run all Agentic Harness Policy Pack checks on a file."""
    # Early exit: skip files without agent-related patterns
    if not _AGENT_MARKERS.search(content):
        return

    _check_inline_tool_def(content=content, lines=lines, add_issue=add_issue)
    _check_prompt_only_permission(content=content, lines=lines, add_issue=add_issue)
    _check_no_session_persistence(content=content, lines=lines, add_issue=add_issue)
    _check_state_conflation(content=content, lines=lines, add_issue=add_issue)
    _check_no_budget_check(content=content, lines=lines, add_issue=add_issue)
    _check_unverified_handoff(content=content, lines=lines, add_issue=add_issue)
    _check_unbounded_history(content=content, lines=lines, add_issue=add_issue)
    _check_static_tool_pool(content=content, lines=lines, add_issue=add_issue)


# ── 1. AGENT-PY-INLINE-TOOL-DEF ────────────────────────────────────

# Matches strings that describe tools inline in a prompt
_INLINE_TOOL_PHRASES = re.compile(
    r"You have (?:access to )?(?:the following )?tools|"
    r"Available tools:|"
    r"Use them",
    re.IGNORECASE,
)


def _check_inline_tool_def(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-INLINE-TOOL-DEF: tool definitions in prompt strings."""
    # Only flag if the file also has LLM calls
    if not _LLM_CALL.search(content):
        return

    for i, line in enumerate(lines):
        if _INLINE_TOOL_PHRASES.search(line):
            add_issue(
                line=i + 1,
                rule="AGENT-PY-INLINE-TOOL-DEF",
                severity="warning",
                message=(
                    "Tool definitions are embedded in a prompt string. "
                    "Inline tool specs drift out of sync with actual tool implementations."
                ),
                suggestion=(
                    "Agentic Design Principle: generate tool descriptions from "
                    "code (docstrings / JSON-Schema). Use a tool registry so the "
                    "prompt always reflects the real tool surface."
                ),
            )
            return  # one finding per file is sufficient


# ── 2. AGENT-PY-PROMPT-ONLY-PERMISSION ─────────────────────────────

_PROMPT_PERMISSION_PHRASES = re.compile(
    r"\bNEVER\b|must not|not allowed|Do not call", re.IGNORECASE
)

_PROMPT_PERMISSION_CONTEXT = re.compile(
    r"\btool\b|\bdelete\b|\bwrite\b|\bdestruct", re.IGNORECASE
)

_CODE_PERMISSION_PATTERNS = re.compile(
    r"PermissionDenied|permission_engine|\.check\(|\.enforce\(|"
    r"\.authorize\(|permission|PERMISSION",
)


def _check_prompt_only_permission(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-PROMPT-ONLY-PERMISSION: permissions only in prompt text."""
    # Does the file have code-level permission enforcement?
    has_code_permission = bool(_CODE_PERMISSION_PATTERNS.search(content))
    if has_code_permission:
        return

    for i, line in enumerate(lines):
        if _PROMPT_PERMISSION_PHRASES.search(line) and _PROMPT_PERMISSION_CONTEXT.search(line):
            add_issue(
                line=i + 1,
                rule="AGENT-PY-PROMPT-ONLY-PERMISSION",
                severity="error",
                message=(
                    "Permission enforcement exists only in prompt text. "
                    "An LLM can ignore prompt instructions; permissions must be "
                    "enforced in harness code."
                ),
                suggestion=(
                    "Agentic Design Principle: enforce permissions in the harness, "
                    "not the prompt. Add a code-level permission check "
                    "(e.g., permission_engine.check()) before tool execution."
                ),
            )
            return  # one finding per file


# ── 3. AGENT-PY-NO-SESSION-PERSISTENCE ─────────────────────────────

_WHILE_PATTERN = re.compile(r"^\s*while\b")
_TOOL_EXEC_PATTERN = re.compile(
    r"execute_tool|execute\(|invoke_tool|tool_call|\.run\(|\.execute\("
)
_CHECKPOINT_PATTERN = re.compile(
    r"checkpoint|\.save\(|persist|store\.checkpoint"
)


def _check_no_session_persistence(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-NO-SESSION-PERSISTENCE: agent loop without checkpoint."""
    i = 0
    while i < len(lines):
        if not _WHILE_PATTERN.match(lines[i]):
            i += 1
            continue

        while_line = i
        while_indent = len(lines[i]) - len(lines[i].lstrip())

        has_tool_exec = False
        has_checkpoint = False
        j = i + 1

        while j < len(lines) and j < i + 40:
            line = lines[j]
            stripped = line.strip()

            if stripped and not stripped.startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= while_indent:
                    break

            if _TOOL_EXEC_PATTERN.search(line):
                has_tool_exec = True
            if _CHECKPOINT_PATTERN.search(line):
                has_checkpoint = True

            j += 1

        if has_tool_exec and not has_checkpoint:
            add_issue(
                line=while_line + 1,
                rule="AGENT-PY-NO-SESSION-PERSISTENCE",
                severity="warning",
                message=(
                    "Agent loop executes tools but never checkpoints session state. "
                    "A crash mid-loop loses all progress."
                ),
                suggestion=(
                    "Agentic Design Principle: persist session state after each tool "
                    "execution. Add session_store.checkpoint(session) or equivalent "
                    "after recording tool results."
                ),
            )

        i = j if j > i + 1 else i + 1


# ── 4. AGENT-PY-STATE-CONFLATION ───────────────────────────────────

_STATE_IN_MESSAGES = re.compile(
    r"messages\.append\(.*(?:workflow_state|step_output|step.*complete|progress)"
)


def _check_state_conflation(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-STATE-CONFLATION: workflow state in message lists."""
    for i, line in enumerate(lines):
        if _STATE_IN_MESSAGES.search(line):
            add_issue(
                line=i + 1,
                rule="AGENT-PY-STATE-CONFLATION",
                severity="warning",
                message=(
                    "Workflow state is appended directly to the conversation "
                    "message list. This conflates orchestration state with "
                    "LLM context, making debugging and replay difficult."
                ),
                suggestion=(
                    "Agentic Design Principle: keep workflow state separate from "
                    "conversation history. Use a structured context builder "
                    "(e.g., build_turn_context()) to inject state at prompt-assembly time."
                ),
            )
            return  # one finding per file


# ── 5. AGENT-PY-NO-BUDGET-CHECK ────────────────────────────────────

_LOOP_START = re.compile(r"^\s*(?:for|while)\b")
_MODEL_INVOKE = re.compile(
    r"\b(?:model|llm)\.invoke\b"
)
_BUDGET_CHECK = re.compile(
    r"budget\.check|estimate_tokens|token_budget"
)


def _check_no_budget_check(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-NO-BUDGET-CHECK: LLM call in loop without budget check."""
    i = 0
    while i < len(lines):
        if not _LOOP_START.match(lines[i]):
            i += 1
            continue

        loop_line = i
        loop_indent = len(lines[i]) - len(lines[i].lstrip())

        has_model_invoke = False
        has_budget_check = False
        model_invoke_line = 0
        j = i + 1

        while j < len(lines) and j < i + 30:
            line = lines[j]
            stripped = line.strip()

            if stripped and not stripped.startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= loop_indent:
                    break

            if _MODEL_INVOKE.search(line):
                has_model_invoke = True
                model_invoke_line = j
            if _BUDGET_CHECK.search(line):
                has_budget_check = True

            j += 1

        if has_model_invoke and not has_budget_check:
            add_issue(
                line=model_invoke_line + 1,
                rule="AGENT-PY-NO-BUDGET-CHECK",
                severity="warning",
                message=(
                    "LLM call inside a loop without a token budget check. "
                    "Unbounded loops can silently exhaust token budgets."
                ),
                suggestion=(
                    "Agentic Design Principle: check token budget before each LLM call. "
                    "Add budget.check(estimate_tokens(context)) before the model.invoke() "
                    "call to enforce spending limits."
                ),
            )

        i = j if j > i + 1 else i + 1


# ── 6. AGENT-PY-UNVERIFIED-HANDOFF ─────────────────────────────────

_RESULT_ASSIGN = re.compile(
    r"^\s*(\w+)\s*=\s*\w+\.(?:run|execute)\("
)
_HANDOFF_CALL = re.compile(
    r"\w+\.(?:process|handle|run)\("
)
_VERIFY_PATTERN = re.compile(
    r"verify|check|validate", re.IGNORECASE
)


def _check_unverified_handoff(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-UNVERIFIED-HANDOFF: direct output passing between agents."""
    i = 0
    while i < len(lines):
        m = _RESULT_ASSIGN.match(lines[i])
        if not m:
            i += 1
            continue

        result_var = m.group(1)
        # Look at the lines between this assignment and the next handoff
        # to see if there's a verify/check/validate call
        j = i + 1
        found_verify = False
        while j < len(lines) and j < i + 10:
            line = lines[j]
            stripped = line.strip()

            # Check if this line hands off the result
            if _HANDOFF_CALL.search(line) and result_var in line:
                if not found_verify:
                    add_issue(
                        line=j + 1,
                        rule="AGENT-PY-UNVERIFIED-HANDOFF",
                        severity="warning",
                        message=(
                            "Output from one agent/executor is passed directly "
                            "to another without verification. Unverified handoffs "
                            "propagate errors across agent boundaries."
                        ),
                        suggestion=(
                            "Agentic Design Principle: verify outputs at every handoff "
                            "boundary. Add a verification step (e.g., verifier.check()) "
                            "between the producer and consumer agents."
                        ),
                    )
                    return  # one finding per file
                break

            if _VERIFY_PATTERN.search(line):
                found_verify = True

            j += 1

        i += 1


# ── 7. AGENT-PY-UNBOUNDED-HISTORY ──────────────────────────────────

_WHILE_TRUE = re.compile(r"^\s*while\s+True\s*:")
_MSG_APPEND = re.compile(r"messages\.append\(")
_MSG_SLICE = re.compile(r"messages\[[-\w.:]+\]")


def _check_unbounded_history(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-UNBOUNDED-HISTORY: messages grow without windowing."""
    i = 0
    while i < len(lines):
        if not _WHILE_TRUE.match(lines[i]):
            i += 1
            continue

        while_line = i
        while_indent = len(lines[i]) - len(lines[i].lstrip())

        has_append = False
        has_slice = False
        j = i + 1

        while j < len(lines) and j < i + 30:
            line = lines[j]
            stripped = line.strip()

            if stripped and not stripped.startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= while_indent:
                    break

            if _MSG_APPEND.search(line):
                has_append = True
            if _MSG_SLICE.search(line):
                has_slice = True

            j += 1

        if has_append and not has_slice:
            add_issue(
                line=while_line + 1,
                rule="AGENT-PY-UNBOUNDED-HISTORY",
                severity="warning",
                message=(
                    "Message list grows inside a while-True loop without "
                    "windowing. Long conversations will exceed context limits "
                    "and degrade response quality."
                ),
                suggestion=(
                    "Agentic Design Principle: apply a sliding window to message "
                    "history. Use messages[-MAX_TURNS:] or a summarisation step "
                    "to keep context within token limits."
                ),
            )

        i = j if j > i + 1 else i + 1


# ── 8. AGENT-PY-STATIC-TOOL-POOL ───────────────────────────────────

_ALL_TOOLS_ASSIGN = re.compile(
    r"^\s*(\w+)\s*=\s*\w+\.get_all(?:_tools)?\("
)
_FOR_WHILE = re.compile(r"^\s*(?:for|while)\b")


def _check_static_tool_pool(
    *, content: str, lines: list[str], add_issue: Callable
) -> None:
    """AGENT-PY-STATIC-TOOL-POOL: same tools on every loop turn."""
    i = 0
    while i < len(lines):
        m = _ALL_TOOLS_ASSIGN.match(lines[i])
        if not m:
            i += 1
            continue

        tool_var = m.group(1)
        assign_line = i

        # Look for a for/while loop after this assignment that uses tool_var
        j = i + 1
        while j < len(lines):
            if _FOR_WHILE.match(lines[j]):
                # Scan the loop body for tools=<tool_var>
                loop_indent = len(lines[j]) - len(lines[j].lstrip())
                k = j + 1
                while k < len(lines) and k < j + 30:
                    line = lines[k]
                    stripped = line.strip()

                    if stripped and not stripped.startswith("#"):
                        line_indent = len(line) - len(line.lstrip())
                        if line_indent <= loop_indent:
                            break

                    if re.search(rf"tools\s*=\s*{re.escape(tool_var)}\b", line):
                        add_issue(
                            line=assign_line + 1,
                            rule="AGENT-PY-STATIC-TOOL-POOL",
                            severity="info",
                            message=(
                                f"Static tool pool '{tool_var}' is used for every "
                                "turn of a multi-step loop. Each step may only need "
                                "a subset of tools."
                            ),
                            suggestion=(
                                "Agentic Design Principle: select tools per step. "
                                "Use registry.get_tools(tags=step.required_tags) to "
                                "provide only the tools relevant to the current step, "
                                "reducing prompt size and tool confusion."
                            ),
                        )
                        return  # one finding per file

                    k += 1
                break  # only check the first loop after assignment
            j += 1

        i += 1
