from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from observatory.events import append_event, normalize_claude_hook, read_events  # noqa: E402
from observatory.health import SnapshotBuilder  # noqa: E402
from observatory.install_hooks import HOOK_COMMAND, HOOK_EVENTS, install  # noqa: E402


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_jsonl(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def test_hook_normalization_is_private_by_default(tmp_path):
    payload = {
        "hook_event_name": "PreToolUse", "session_id": "session-1", "cwd": str(tmp_path),
        "tool_name": "Bash", "tool_use_id": "call-1",
        "tool_input": {"command": "deploy --token secret-value", "api_key": "sk-test"},
    }
    event = normalize_claude_hook(payload, received_at="2026-07-11T12:00:00+00:00")
    assert "tool_input" not in event["details"]
    captured = normalize_claude_hook(payload, capture_inputs=True,
                                     received_at="2026-07-11T12:00:01+00:00")
    assert captured["details"]["tool_input"]["api_key"] == "<redacted>"
    assert captured["details"]["tool_input"]["command"].startswith("deploy")


def test_event_round_trip_and_agent_projection(tmp_path):
    event = normalize_claude_hook({
        "hook_event_name": "PostToolUseFailure", "session_id": "session-1",
        "cwd": str(tmp_path), "tool_name": "Bash", "error": "tests failed",
    }, received_at="2026-07-11T12:00:00+00:00")
    append_event(tmp_path, event)
    assert read_events(tmp_path) == [event]
    snapshot = SnapshotBuilder(tmp_path).build()
    assert snapshot["agents"][0]["state"] == "error"
    assert snapshot["agents"][0]["activity"] == "PostToolUseFailure"


def test_long_context_is_labelled_as_activity_not_exact_utilization(tmp_path):
    _write_jsonl(tmp_path / ".claude" / "ctx" / "checkpoints.jsonl", [{
        "ts": "2026-07-11T12:00:00+00:00", "session": "long-session", "turns": 1200,
        "conflicts": 0, "gist_bpe": 1900,
        "stats": {"errors": 7, "files_changed": 24, "decisions": 5},
    }])
    snapshot = SnapshotBuilder(tmp_path).build()
    context = snapshot["contexts"][0]
    assert context["activity_pressure"] == 100
    assert "not provider context-window" in context["measurement"]
    assert any(item["id"] == "context-long-long-session" for item in snapshot["attention"])


def test_vacuous_quality_and_missing_eval_never_look_green(tmp_path):
    _write_json(tmp_path / ".quality-reports" / "report_1.json", {
        "passed": True, "stats": {"files_checked": 0}, "issues": [],
    })
    snapshot = SnapshotBuilder(tmp_path).build()
    gates = {gate["id"]: gate for gate in snapshot["gates"]}
    assert gates["quality"]["status"] == "inconclusive"
    assert gates["eval"]["status"] == "missing"
    ids = {item["id"] for item in snapshot["attention"]}
    assert {"quality-vacuous", "eval-missing"} <= ids


def test_worktree_inventory_does_not_claim_unknown_trees_are_orphans(tmp_path):
    for index in range(5):
        worktree = tmp_path / ".claude" / "worktrees" / f"agent-{index}"
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: somewhere", encoding="utf-8")
    snapshot = SnapshotBuilder(tmp_path).build()
    assert len(snapshot["worktrees"]) == 5
    assert {tree["classification"] for tree in snapshot["worktrees"]} == {"activity unknown"}
    assert any(item["id"] == "worktree-inventory" for item in snapshot["attention"])


def test_hook_installer_merges_and_is_idempotent(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    _write_json(settings, {"hooks": {"PreCompact": [{"hooks": [
        {"type": "command", "command": "python -m ctxpack hook pre-compact"}
    ]}]}})
    _, first_added = install(tmp_path)
    _, second_added = install(tmp_path)
    installed = json.loads(settings.read_text(encoding="utf-8"))
    assert set(first_added) == set(HOOK_EVENTS)
    assert second_added == []
    assert installed["hooks"]["PreCompact"][0]["hooks"][0]["command"].startswith("python -m ctxpack")
    commands = [hook["command"] for entry in installed["hooks"]["PreCompact"]
                for hook in entry.get("hooks", [])]
    assert commands.count(HOOK_COMMAND) == 1

