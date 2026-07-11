"""Canonical context/session projection shared by the base snapshot and the
CtxPack memory adapter.

Both the base health snapshot and ``CtxPackMemoryAdapter`` read the same
``.claude/ctx/checkpoints.jsonl`` ledger and both need turns, activity pressure,
a pressure level, and the long-running-context concern. Computing that in one
place removes the duplicated logic that previously drifted between the two.

The pressure meter measures *conversation activity* — turns, checkpoints, files
changed — and is deliberately NOT presented as provider context-window
utilization, which hooks cannot observe. The thresholds are product defaults,
not a provider limit.
"""

from __future__ import annotations

from typing import Any

from .findings import finding
from .sources import as_dict, as_int

MEASUREMENT = "conversation activity; not provider context-window utilization"
LONG_CONTEXT_TURNS = 1000
BUSY_CONTEXT_TURNS = 500


def turns_of(latest: dict[str, Any]) -> int:
    """Turns from the checkpoint row, tolerating the top-level or stats spelling.

    A non-dict ``stats`` or a non-numeric ``turns`` coerces to 0 rather than
    raising — a corrupt ledger row must not take down the snapshot.
    """
    stats = as_dict(latest.get("stats"))
    return as_int(latest.get("turns")) or as_int(stats.get("turns")) or 0


def activity_pressure(turns: int) -> int:
    """A 0-100 activity gauge; saturates so a very long session reads as full."""
    return min(100, round(turns / 10))


def pressure_level(turns: int) -> str:
    """Coarse band used to colour the meter; never 'healthy' once long-running."""
    if turns >= LONG_CONTEXT_TURNS:
        return "high"
    if turns >= BUSY_CONTEXT_TURNS:
        return "medium"
    return "healthy"


def base_session(session_id: str, latest: dict[str, Any], checkpoints: int) -> dict[str, Any]:
    """The session fields common to every context/memory consumer.

    The CtxPack adapter extends this with recall-usage, fidelity, and archive
    fields; the base snapshot uses it as-is.
    """
    stats = as_dict(latest.get("stats"))
    turns = turns_of(latest)
    return {
        "session_id": session_id,
        "turns": turns,
        "activity_pressure": activity_pressure(turns),
        "level": pressure_level(turns),
        "checkpoints": checkpoints,
        "gist_tokens_estimate": latest.get("gist_bpe"),
        "errors": as_int(stats.get("errors")),
        "files_changed": as_int(stats.get("files_changed")),
        "decisions": as_int(stats.get("decisions")),
        "conflicts": as_int(latest.get("conflicts")),
        "last_checkpoint": latest.get("ts"),
        "measurement": MEASUREMENT,
    }


def long_context_finding(session: dict[str, Any]) -> dict[str, Any] | None:
    """A long-running session is a rule-based handoff concern, or ``None``.

    This is the single definition of the ``context-long-*`` finding so the base
    snapshot and the memory adapter cannot disagree about when it fires.
    """
    if session["turns"] < LONG_CONTEXT_TURNS:
        return None
    return finding(
        f"context-long-{session['session_id']}",
        "Long-running context needs a handoff review", "high",
        "The session has accumulated enough turns that stale constraints and "
        "compaction loss deserve review.",
        [{"session": session["session_id"], "turns": session["turns"],
          "checkpoints": session["checkpoints"], "errors": session["errors"],
          "files_changed": session["files_changed"]}],
        "Compact with a verified decision/file summary, or start a fresh task-specific session.",
        classification="rule-based concern", source="ctxpack",
    )
