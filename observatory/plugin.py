"""Composable Observatory projection used by KP_SDLC and adopting repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .health import SnapshotBuilder
from .memory import CtxPackMemoryAdapter, MemoryAdapter


class ObservatoryPlugin:
    """Add provider assessments to the stable repository snapshot.

    Other repositories can pass their own MemoryAdapter implementations. The
    base health projector remains useful when no memory provider is installed.
    """

    plugin_id = "kp-sdlc/agent-observatory@1"

    def __init__(self, root: Path, *, memory_adapters: list[MemoryAdapter] | None = None):
        self.root = root.resolve()
        self.memory_adapters = memory_adapters or [CtxPackMemoryAdapter(self.root)]

    def snapshot(self) -> dict[str, Any]:
        snapshot = SnapshotBuilder(self.root).build()
        assessments = [adapter.assess() for adapter in self.memory_adapters]
        snapshot["plugin"] = self.plugin_id
        snapshot["memory"] = assessments
        sessions = [session for assessment in assessments for session in assessment.get("sessions", [])]
        snapshot["contexts"] = sessions
        snapshot["summary"]["context_sessions"] = len(sessions)

        # The memory adapter is the single owner of memory/context health. Drop the
        # base snapshot's ctxpack-sourced context findings so the same concern is not
        # counted twice (once by the base _contexts projection, once by the adapter).
        base_attention = [item for item in snapshot["attention"] if item.get("source") != "ctxpack"]
        memory_attention = [finding for assessment in assessments
                            for finding in assessment.get("findings", [])]
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        snapshot["attention"] = sorted(
            base_attention + memory_attention,
            key=lambda item: (rank.get(item["severity"], 9), item["title"]),
        )[:30]
        snapshot["summary"]["needs_attention"] = sum(
            item["severity"] in {"critical", "high"} for item in snapshot["attention"]
        )
        return snapshot

