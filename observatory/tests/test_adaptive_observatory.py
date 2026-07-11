from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from observatory.adaptive import AdaptiveObservatory  # noqa: E402
from observatory.memory import CtxPackMemoryAdapter  # noqa: E402
from observatory.maturity import MaturityEngine  # noqa: E402
from observatory.telemetry import ClaudeCodeTelemetryAdapter  # noqa: E402


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def _ctx_settings():
    return {"hooks": {name: [{"hooks": [{"type": "command", "command": f"ctxpack {name}"}]}]
                      for name in ("PreCompact", "SessionStart", "Stop", "SessionEnd")}}


def test_ctxpack_adapter_assesses_every_memory_mechanism(tmp_path):
    _write_json(tmp_path / ".claude" / "settings.json", _ctx_settings())
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {"ctxpack": {"command": "python"}}})
    session_id = "12345678-abcd"
    _write_jsonl(tmp_path / ".claude" / "ctx" / "checkpoints.jsonl", [{
        "session": session_id, "turns": 200, "conflicts": 0, "literal_fidelity": 1,
        "lint_status": "ok", "stats": {"ledger_reads": 4, "transcript_greps": 1},
    }])
    ctx_dir = tmp_path / ".claude" / "ctx"
    (ctx_dir / "session-12345678.ctx").write_text("archive", encoding="utf-8")
    (ctx_dir / "session-12345678-gist.md").write_text("gist", encoding="utf-8")
    result = CtxPackMemoryAdapter(tmp_path).assess()
    assert result["status"] == "healthy"
    assert all(result["capabilities"].values())
    assert result["sessions"][0]["has_archive"] is True
    assert result["sessions"][0]["has_gist"] is True


def test_ctxpack_adapter_calls_out_transcript_fallback_dominance(tmp_path):
    _write_json(tmp_path / ".claude" / "settings.json", _ctx_settings())
    _write_json(tmp_path / ".mcp.json", {"mcpServers": {"ctxpack": {"command": "python"}}})
    _write_jsonl(tmp_path / ".claude" / "ctx" / "checkpoints.jsonl", [{
        "session": "s", "turns": 100, "stats": {"ledger_reads": 0, "transcript_greps": 5},
    }])
    result = CtxPackMemoryAdapter(tmp_path).assess()
    assert result["status"] == "degraded"
    assert any(item["id"] == "memory-fallback-s" for item in result["findings"])


def test_claude_adapter_reports_capabilities_not_just_vendor_events(tmp_path):
    _write_json(tmp_path / ".claude" / "settings.json", {"hooks": {
        "SessionStart": [{}], "PreToolUse": [{}], "PostToolUse": [{}],
        "SubagentStart": [{}], "SubagentStop": [{}], "PreCompact": [{}],
    }})
    report = ClaudeCodeTelemetryAdapter(tmp_path).probe()
    assert report["detected"] is True
    assert report["capabilities"]["session_lifecycle"] is True
    assert report["capabilities"]["tool_lifecycle"] is True
    assert report["capabilities"]["subagents"] is True


def test_maturity_history_records_only_changed_evidence(tmp_path):
    snapshot = {
        "memory": [], "gates": [], "worktrees": [],
        "summary": {"events_observed": 0},
    }
    engine = MaturityEngine(tmp_path)
    assessment = engine.evaluate(snapshot, [])
    _, first = engine.record(assessment)
    _, second = engine.record(assessment)
    assert first is True
    assert second is False
    assert len(engine.history()) == 1


def test_adaptive_snapshot_exposes_adapter_and_maturity_contracts(tmp_path):
    snapshot = AdaptiveObservatory(tmp_path).snapshot()
    assert snapshot["plugin"] == "kp-sdlc/adaptive-observatory@1"
    assert snapshot["telemetry"][0]["adapter"] == "claude-code/hooks@1"
    dimension_ids = {item["id"] for item in snapshot["maturity"]["dimensions"]}
    assert {"observability", "memory", "quality_governance", "evaluation",
            "parallel_coordination"} == dimension_ids

