"""Pluggable memory/context health adapters.

CtxPack owns capture, compaction, recall, and durable session memory. Observatory
only assesses whether those mechanisms are present, fresh, and actually used — it
never copies the ledger, performs recall, compacts, or rewrites gists.

``CtxPackMemoryAdapter.assess`` is deliberately decomposed into small stages —
configuration coverage, per-session projection, session findings, configuration
findings, and status assembly — so each stays readable and independently
verifiable while preserving the exact evidence and fail-closed status the
dashboard depends on.
"""

from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import Any, Protocol

from .context import base_session, long_context_finding
from .findings import finding
from .sources import as_dict, as_float, as_int, read_json, read_jsonl


class MemoryAdapter(Protocol):
    """Stable boundary for CtxPack or another repository memory provider."""

    provider_id: str

    def assess(self) -> dict[str, Any]: ...


def _commands_for(settings: dict[str, Any], event_name: str) -> list[str]:
    """Every hook command string configured for one lifecycle event (flattened)."""
    entries = (settings.get("hooks") or {}).get(event_name, [])
    hooks = chain.from_iterable(entry.get("hooks", []) for entry in entries if isinstance(entry, dict))
    return [hook["command"] for hook in hooks
            if isinstance(hook, dict) and isinstance(hook.get("command"), str)]


class CtxPackMemoryAdapter:
    provider_id = "ctxpack"
    _REQUIRED_HOOKS = ("PreCompact", "SessionStart", "Stop", "SessionEnd")

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._ctx_dir = self.root / ".claude" / "ctx"

    def assess(self) -> dict[str, Any]:
        settings = read_json(self.root / ".claude" / "settings.json") or {}
        mcp = read_json(self.root / ".mcp.json") or {}
        checkpoint_rows = read_jsonl(self._ctx_dir / "checkpoints.jsonl")
        configured_hooks = self._configured_hooks(settings)
        mcp_configured = "ctxpack" in (mcp.get("mcpServers") or {})

        sessions, findings = self._project_sessions(checkpoint_rows)
        findings.extend(self._configuration_findings(configured_hooks, mcp_configured))
        sessions.sort(key=lambda value: value["turns"], reverse=True)

        usage = {
            "ledger_reads": sum(session["ledger_reads"] for session in sessions),
            "transcript_greps": sum(session["transcript_greps"] for session in sessions),
        }
        return {
            "provider": self.provider_id,
            "status": self._status(configured_hooks, mcp_configured, sessions, findings),
            "capabilities": {
                "checkpoint_capture": bool(checkpoint_rows),
                "compaction_capture": configured_hooks["PreCompact"],
                "session_injection": configured_hooks["SessionStart"],
                "session_finalization": configured_hooks["Stop"] and configured_hooks["SessionEnd"],
                "structured_recall": mcp_configured,
            },
            "usage": usage,
            "sessions": sessions,
            "findings": findings,
        }

    def _configured_hooks(self, settings: dict[str, Any]) -> dict[str, bool]:
        """Which required lifecycle hooks actually invoke a ctxpack command."""
        return {
            event: any("ctxpack" in command.lower() for command in _commands_for(settings, event))
            for event in self._REQUIRED_HOOKS
        }

    def _project_sessions(self, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """One enriched session record and its findings per ledger session."""
        latest_by_session: dict[str, dict[str, Any]] = {}
        counts: dict[str, int] = {}
        for row in rows:
            session_id = str(row.get("session") or "unknown")
            latest_by_session[session_id] = row
            counts[session_id] = counts.get(session_id, 0) + 1

        sessions, findings = [], []
        for session_id, latest in latest_by_session.items():
            session = self._project_session(session_id, latest, counts[session_id])
            sessions.append(session)
            findings.extend(self._session_findings(session))
        return sessions, findings

    def _project_session(self, session_id: str, latest: dict[str, Any], checkpoints: int) -> dict[str, Any]:
        """The shared base session enriched with CtxPack recall/fidelity evidence."""
        stats = as_dict(latest.get("stats"))
        prefix = f"session-{session_id[:8]}"
        archives = {suffix: (self._ctx_dir / f"{prefix}{suffix}").exists()
                    for suffix in (".ctx", "-gist.md")}
        session = base_session(session_id, latest, checkpoints)
        session.update({
            "ledger_reads": as_int(stats.get("ledger_reads")),
            "transcript_greps": as_int(stats.get("transcript_greps")),
            "literal_fidelity": latest.get("literal_fidelity"),
            "lint_status": latest.get("lint_status"),
            "has_archive": archives[".ctx"],
            "has_gist": archives["-gist.md"],
        })
        return session

    @staticmethod
    def _session_findings(session: dict[str, Any]) -> list[dict[str, Any]]:
        """Long-context, integrity, recall-fallback, and fidelity concerns for one session."""
        session_id = session["session_id"]
        findings = []
        concern = long_context_finding(session)
        if concern is not None:
            findings.append(concern)
        if session["conflicts"] > 0 or session["lint_status"] not in {None, "ok"}:
            findings.append(finding(
                f"memory-integrity-{session_id}", "Memory ledger integrity needs attention", "high",
                "CtxPack reported a conflict or non-OK ledger lint status.",
                [{"session": session_id, "conflicts": session["conflicts"],
                  "lint_status": session["lint_status"]}],
                "Resolve contradictory decisions before further implementation.", source="ctxpack"))
        greps, reads = session["transcript_greps"], session["ledger_reads"]
        if greps >= 3 and greps > reads:
            findings.append(finding(
                f"memory-fallback-{session_id}", "Raw transcript fallback dominates memory recall", "medium",
                "The session used raw transcript searches more often than the structured CtxPack read path.",
                [{"session": session_id, "ledger_reads": reads, "transcript_greps": greps}],
                "Use ctx/session_recall, timeline, decisions, why, or graph_query before transcript grep.",
                source="ctxpack"))
        raw_fidelity = session["literal_fidelity"]
        fidelity = as_float(raw_fidelity)
        if raw_fidelity is not None and (fidelity is None or fidelity < 1):
            findings.append(finding(
                f"memory-fidelity-{session_id}", "Memory literal fidelity is incomplete", "high",
                "An exact identifier was not recovered by the checkpoint ledger, or the "
                "recorded fidelity is not a clean 1.0 (a non-numeric value is worse, not safer).",
                [{"session": session_id, "literal_fidelity": raw_fidelity}],
                "Inspect the checkpoint and restore missing exact identifiers before handoff.",
                source="ctxpack"))
        return findings

    def _configuration_findings(self, configured_hooks: dict[str, bool],
                                mcp_configured: bool) -> list[dict[str, Any]]:
        """Concerns about the memory system's own wiring, independent of any session."""
        findings = []
        missing_hooks = [name for name, present in configured_hooks.items() if not present]
        if missing_hooks:
            findings.append(finding(
                "memory-hooks-missing", "CtxPack lifecycle capture is incomplete", "high",
                "One or more lifecycle hooks required for start, compaction, stop, and end coverage are missing.",
                [{"missing_hooks": missing_hooks, "configured_hooks": configured_hooks}],
                "Install the missing CtxPack hooks without replacing existing project hooks.",
                source="ctxpack"))
        if not mcp_configured:
            findings.append(finding(
                "memory-recall-unavailable", "CtxPack structured recall is not configured", "medium",
                "The repository MCP configuration does not expose the CtxPack recall tools.",
                [{"path": str(self.root / ".mcp.json")}],
                "Configure the ctxpack MCP server or document the alternative structured recall path.",
                source="ctxpack"))
        return findings

    @staticmethod
    def _status(configured_hooks: dict[str, bool], mcp_configured: bool,
                sessions: list[dict[str, Any]], findings: list[dict[str, Any]]) -> str:
        """Fail-closed status: any finding is degraded; full wiring with no findings is healthy."""
        if findings:
            return "degraded"
        complete = all(configured_hooks.values()) and mcp_configured and bool(sessions)
        return "healthy" if complete else "unavailable"
