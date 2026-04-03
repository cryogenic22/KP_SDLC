"""CK-AGENTIC-HARNESS — Agentic Harness Architecture Policy.

Project-level policy that scans the entire codebase to determine whether
the 9 infrastructure modules required by the Agentic System Design
Principles are present.  For each missing module, emits a finding with
actionable fix options and risk context.

Only fires when the codebase appears to be an agentic system (contains
agent-related patterns such as invoke, tool_call, agent, workflow).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path

# ── module definitions ────────────────────────────────────────────────

# Each tuple: (module_key, display_name, severity, patterns, why, fix_options)
_MODULE_DEFS: List[Tuple[str, str, str, List[str], str, List[str]]] = [
    (
        "tool_registry",
        "Tool Registry",
        "medium",
        [r"\bregister\b", r"\bToolRegistry\b", r"\btool_registry\b", r"\b_REGISTRY\b", r"@register_tool\b"],
        (
            "Without a tool registry, agents cannot discover or validate tools "
            "at runtime. This leads to hard-coded tool references that break "
            "when tools are added, removed, or renamed."
        ),
        [
            "Create a ToolRegistry class that maps tool names to callables.",
            "Add a @register_tool decorator for automatic registration.",
            "Expose a list_tools() method for agent introspection.",
        ],
    ),
    (
        "permission_system",
        "Permission System",
        "high",
        [r"\btrust_tier\b", r"\bPermissionDenied\b", r"\bpermission_engine\b", r"\bauthorize\b", r"\bTrustTier\b"],
        (
            "An agentic system without a permission layer has no guardrails. "
            "Any agent can invoke any tool with any arguments, creating serious "
            "security and safety risks including data exfiltration and "
            "unintended side-effects."
        ),
        [
            "Implement a TrustTier enum (e.g. UNTRUSTED, USER, SYSTEM).",
            "Create a permission_engine that maps (agent, tool, tier) to allow/deny.",
            "Raise PermissionDenied on unauthorized access attempts.",
        ],
    ),
    (
        "session_persistence",
        "Session Persistence",
        "high",
        [r"\bcheckpoint\b", r"\bsession_store\b", r"\bSessionStore\b", r"\bresume_or_start\b", r"\bsave_session\b"],
        (
            "Without session persistence, a crash or timeout loses all agent "
            "progress. Long-running agentic workflows must be resumable to "
            "avoid wasted compute and broken user expectations."
        ),
        [
            "Implement a SessionStore that serialises workflow state to disk or DB.",
            "Add checkpoint() calls at each significant step.",
            "Provide a resume_or_start() entry point that rehydrates state.",
        ],
    ),
    (
        "state_separation",
        "State Separation",
        "medium",
        [r"\bworkflow_state\b", r"\bWorkflowState\b", r"\bbuild_context\b", r"\bbuild_turn_context\b"],
        (
            "Mixing session state, turn context, and workflow state into a "
            "single blob makes it impossible to reason about what the agent "
            "sees at each step. Clear state separation prevents context "
            "pollution and simplifies debugging."
        ),
        [
            "Define a WorkflowState dataclass for persistent cross-turn state.",
            "Build a build_turn_context() function that assembles per-turn input.",
            "Keep ephemeral turn data separate from durable workflow state.",
        ],
    ),
    (
        "token_budget",
        "Token Budget",
        "medium",
        [r"\bTokenBudget\b", r"\btoken_budget\b", r"\bbudget\.check\b", r"\bestimate_tokens\b", r"\bmax_tokens\b"],
        (
            "Without explicit token budget management, agents can silently "
            "exceed context windows, leading to truncated prompts, lost "
            "instructions, and degraded output quality."
        ),
        [
            "Create a TokenBudget class tracking used vs. available tokens.",
            "Add estimate_tokens() for pre-flight cost checks.",
            "Enforce budget.check() before each LLM call.",
        ],
    ),
    (
        "observability",
        "Observability",
        "medium",
        [r"\bEventStream\b", r"\bevent_stream\b", r"\bemit_event\b", r"\bAgentEvent\b"],
        (
            "Agentic systems are inherently non-deterministic. Without "
            "structured event logging, debugging multi-step failures is "
            "nearly impossible and production monitoring is blind."
        ),
        [
            "Implement an EventStream that records AgentEvent objects.",
            "Add emit_event() calls at tool invocations and decision points.",
            "Ensure events are structured (JSON) and include timestamps.",
        ],
    ),
    (
        "verification_layer",
        "Verification Layer",
        "medium",
        [r"\bverify\b", r"\bVerifier\b", r"\bVerificationResult\b", r"\bverification\.passed\b", r"\bpostcondition\b"],
        (
            "Agents make mistakes. Without a verification layer, outputs go "
            "unchecked, and errors propagate downstream. Postcondition checks "
            "catch bad tool results before they corrupt workflow state."
        ),
        [
            "Create a Verifier base class with a verify() method.",
            "Return VerificationResult with passed/failed status and reason.",
            "Run postcondition checks after every tool execution.",
        ],
    ),
    (
        "agent_types",
        "Agent Types",
        "medium",
        [r"\bAgentType\b", r"\bagent_type\b", r"\bOrchestrator\b", r"\bExecutor\b", r"\bRetriever\b", r"\bHandoffContract\b"],
        (
            "Without explicit agent type roles (orchestrator, executor, "
            "retriever), responsibility boundaries blur. Agents end up doing "
            "everything, making the system hard to test and reason about."
        ),
        [
            "Define an AgentType enum (Orchestrator, Executor, Retriever).",
            "Assign each agent a single type that constrains its capabilities.",
            "Use HandoffContract to define inter-agent communication rules.",
        ],
    ),
    (
        "harness_pattern",
        "Harness Pattern",
        "medium",
        [r"\bAgentHarness\b", r"\bHarness\b", r"\bharness\.run\b", r"\bharness_config\b"],
        (
            "The harness is the top-level orchestrator that ties all "
            "infrastructure modules together. Without it, each module is "
            "wired ad-hoc, leading to inconsistent initialization and "
            "missed cross-cutting concerns."
        ),
        [
            "Create an AgentHarness class that owns the run loop.",
            "Inject all infrastructure (registry, permissions, budget) via config.",
            "Expose harness.run() as the single entry point for agent execution.",
        ],
    ),
]

# Patterns that indicate this codebase is agentic in nature.
# Use looser matching so compound identifiers like "MyAgent" still match.
_AGENTIC_INDICATORS = [
    re.compile(r"\binvoke\b", re.IGNORECASE),
    re.compile(r"\btool_call\b", re.IGNORECASE),
    re.compile(r"[Aa]gent"),
    re.compile(r"\bworkflow\b", re.IGNORECASE),
]


# ── helpers ───────────────────────────────────────────────────────────

def _is_agentic_codebase(file_contents: Dict[str, str]) -> bool:
    """Return True only if the codebase contains agent-related patterns.

    A plain CRUD app should not be flagged for missing a harness.
    """
    for content in file_contents.values():
        for pat in _AGENTIC_INDICATORS:
            if pat.search(content):
                return True
    return False


def _content_matches_any(content: str, patterns: List[str]) -> bool:
    """Return True if content matches any of the given regex patterns."""
    for pat_str in patterns:
        if re.search(pat_str, content):
            return True
    return False


# ── public API ────────────────────────────────────────────────────────

def check_agentic_harness_policy(
    *,
    root: Path,
    files: List[Path],
    file_contents: Dict[str, str],
) -> List[Finding]:
    """Scan the codebase for evidence of 9 agentic infrastructure modules.

    For each module whose patterns are NOT found in any file, emit a
    finding with policy_id ``CK-AGENTIC-HARNESS``.
    """
    # Gate: only flag agentic codebases
    if not _is_agentic_codebase(file_contents):
        return []

    # Build a list of relative paths for evidence reporting
    scanned_files: List[str] = []
    for f in files:
        try:
            rel = normalize_path(str(f.resolve().relative_to(root.resolve())))
        except (ValueError, OSError):
            rel = normalize_path(str(f))
        scanned_files.append(rel)

    findings: List[Finding] = []

    for module_key, display_name, severity, patterns, why, fix_opts in _MODULE_DEFS:
        found = False
        for content in file_contents.values():
            if _content_matches_any(content, patterns):
                found = True
                break

        if not found:
            findings.append(
                Finding(
                    policy_id="CK-AGENTIC-HARNESS",
                    title=f"No {display_name.lower()} detected",
                    severity=severity,
                    confidence="medium",
                    why_it_matters=why,
                    evidence=[
                        Evidence(
                            file=sf,
                            line=0,
                            snippet="",
                            note=f"Scanned for {display_name} patterns",
                        )
                        for sf in scanned_files[:5]  # cap evidence list
                    ],
                    fix_options=fix_opts,
                    verification=[
                        f"grep -rn '{patterns[0]}' --include='*.py' ."
                    ],
                    metadata={
                        "module": module_key,
                        "found": False,
                        "searched_patterns": patterns,
                    },
                )
            )

    return findings
