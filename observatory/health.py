"""Build a repository-health snapshot from events and existing KP_SDLC artifacts.

``SnapshotBuilder`` is a thin orchestrator: agents come from normalized hook
events, contexts from the CtxPack ledger (via :mod:`observatory.context`),
worktrees from the ``.claude/worktrees`` inventory, and the readiness gates from
:mod:`observatory.gates`. Each projection is small and fail-closed; this class
only assembles them and ranks the attention queue.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .context import base_session, long_context_finding
from .events import read_events
from .findings import finding
from .gates import architecture_gate, eval_gate, quality_gate
from .sources import read_jsonl

SNAPSHOT_SCHEMA = "agent-observatory/snapshot@1"
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_TERMINAL_EVENTS = {"SessionEnd", "Stop", "SubagentStop"}


def _agent_state(event_type: str, details: dict[str, Any]) -> str:
    """Map the latest event for an agent to a coarse display state."""
    if event_type in _TERMINAL_EVENTS:
        return "completed"
    if event_type == "PermissionDenied" or details.get("notification_type") == "permission_prompt":
        return "needs_attention"
    if event_type == "PostToolUseFailure":
        return "error"
    if event_type == "Notification":
        return "waiting"
    return "working"


class SnapshotBuilder:
    """Read-only projection of agent, context, worktree, quality, and eval health."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def build(self) -> dict[str, Any]:
        events = read_events(self.root)
        agents = self._agents(events)
        contexts, context_findings = self._contexts()
        worktrees, worktree_findings = self._worktrees(events)
        gates, gate_findings = self._gates()
        attention = context_findings + worktree_findings + gate_findings
        attention.sort(key=lambda item: (_SEVERITY_RANK.get(item["severity"], 9), item["title"]))
        return {
            "schema": SNAPSHOT_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repository": {"name": self.root.name, "root": str(self.root)},
            "summary": {
                "agents": len(agents),
                "needs_attention": sum(item["severity"] in {"critical", "high"} for item in attention),
                "worktrees": len(worktrees),
                "context_sessions": len(contexts),
                "events_observed": len(events),
            },
            "agents": agents,
            "contexts": contexts,
            "worktrees": worktrees,
            "gates": gates,
            "attention": attention[:30],
            "recent_events": list(reversed(events[-30:])),
        }

    def _agents(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            details = event.get("details") or {}
            identifier = str(details.get("agent_id") or event.get("session_id") or "unknown")
            by_agent[identifier].append(event)
        agents = []
        for identifier, history in by_agent.items():
            latest = history[-1]
            event_type = str(latest.get("event_type") or "Unknown")
            details = latest.get("details") or {}
            agents.append({
                "id": identifier,
                "name": str(details.get("agent_type") or f"session-{identifier[:8]}"),
                "state": _agent_state(event_type, details),
                "activity": event_type,
                "tool": details.get("tool_name"),
                "cwd": latest.get("cwd") or "",
                "last_seen": latest.get("timestamp"),
                "event_count": len(history),
            })
        return sorted(agents, key=lambda agent: (agent["state"] == "completed", agent["name"]))

    def _contexts(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = read_jsonl(self.root / ".claude" / "ctx" / "checkpoints.jsonl")
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("session") or "unknown")].append(row)
        contexts, findings = [], []
        for session_id, history in grouped.items():
            session = base_session(session_id, history[-1], len(history))
            contexts.append(session)
            concern = long_context_finding(session)
            if concern is not None:
                findings.append(concern)
            if session["conflicts"] > 0:
                findings.append(finding(
                    f"context-conflict-{session_id}", "Context ledger contains conflicts", "high",
                    "CtxPack recorded contradictory facts in the session ledger.",
                    [{"session": session_id, "conflicts": session["conflicts"]}],
                    "Resolve the conflicting decisions before further implementation.",
                    source="ctxpack"))
        contexts.sort(key=lambda value: value["turns"], reverse=True)
        return contexts, findings

    def _worktrees(self, events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        base = self.root / ".claude" / "worktrees"
        active_cwds = {str(event.get("cwd") or "").replace("\\", "/").rstrip("/") for event in events}
        worktrees = []
        if base.exists():
            for path in sorted(item for item in base.iterdir() if item.is_dir()):
                path_str = str(path)
                normalized = path_str.replace("\\", "/")
                active = any(cwd == normalized or cwd.startswith(normalized + "/") for cwd in active_cwds)
                worktrees.append({
                    "name": path.name,
                    "path": path_str,
                    "linked": (path / ".git").exists(),
                    "observed_active": active,
                    "classification": "active" if active else "activity unknown",
                })
        count = len(worktrees)
        findings = []
        if count >= 5:
            findings.append(finding(
                "worktree-inventory", "Worktree inventory needs review", "medium",
                f"Claude's worktree directory currently contains {count} worktrees; "
                "event data cannot prove which are safe to remove.",
                [{"count": count, "names": [item["name"] for item in worktrees[:20]]}],
                "Use git worktree list and inspect unmerged or uncommitted changes before pruning anything."))
        return worktrees, findings

    def _gates(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        gates, findings = [], []
        for projection in (quality_gate, architecture_gate, eval_gate):
            gate, gate_findings = projection(self.root)
            gates.append(gate)
            findings.extend(gate_findings)
        return gates, findings
