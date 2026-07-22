"""The meter must produce numbers that are RIGHT, and carry nothing else.

Loop 1's exit gate is exactness: a transcript with hand-computed token counts
must tally to those exact figures, or every downstream claim inherits the error.

The second claim is content-blindness (I1). The extractor reads usage numbers,
message types and tool NAMES — never a tool_use `input`, never assistant text,
and tool results by length only. A fixture plants a secret in each of those
places and asserts none reach the report; the scanner's own teeth are asserted
separately, so "no leak found" cannot pass by having no working scanner.

Third is three-state (I2): absent transcripts report `unavailable` with a
reason. A zero here would read as "this was cheap", which is the one wrong
answer a cost meter must never give.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from observatory import cost  # noqa: E402
from observatory.__main__ import main  # noqa: E402

# Canary content: each string sits somewhere the extractor must not read.
CANARY_TOOL_INPUT = "CANARY-in-a-command"
CANARY_ASSISTANT_TEXT = "CANARY-in-assistant-text"
CANARY_TOOL_RESULT = "CANARYRESULTVALUE"
PLANTED_PATH = "/Users/nobody/private/keys.txt"

# json.dumps("CANARYRESULTVALUE") is the 17 characters plus two quotes.
_EXPECTED_RESULT_BYTES = 19


def _transcript_lines() -> list[str]:
    """Two billed steps, one of them narration; one unbilled tool call; one
    torn line. Every number the tests assert is computable from this list."""
    return [
        json.dumps({
            "type": "assistant", "timestamp": "2026-07-01T00:00:00Z",
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 10, "output_tokens": 100,
                          "cache_read_input_tokens": 1000,
                          "cache_creation_input_tokens": 50},
                "content": [{"type": "tool_use", "name": "Bash",
                             "input": {"command": f"echo {CANARY_TOOL_INPUT} "
                                                  f"{PLANTED_PATH}"}}],
            },
        }),
        json.dumps({
            "type": "user", "timestamp": "2026-07-01T00:01:00Z",
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "content": CANARY_TOOL_RESULT}]},
        }),
        json.dumps({
            "type": "assistant", "timestamp": "2026-07-01T00:02:00Z",
            "message": {
                "role": "assistant",
                "usage": {"input_tokens": 5, "output_tokens": 200,
                          "cache_read_input_tokens": 2000,
                          "cache_creation_input_tokens": 0},
                "content": [{"type": "text", "text": CANARY_ASSISTANT_TEXT}],
            },
        }),
        "this line is not json{{{",
        json.dumps({
            "type": "assistant", "timestamp": "2026-07-01T00:05:00Z",
            "message": {"role": "assistant",
                        "content": [{"type": "tool_use", "name": "Read",
                                     "input": {"file_path": PLANTED_PATH}}]},
        }),
    ]


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A repo and a transcript store laid out the way Claude Code lays them
    out, so the slug resolution is exercised rather than bypassed."""
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    projects = tmp_path / "projects"
    session_dir = cost.transcript_dir_for(repo, projects)
    session_dir.mkdir(parents=True)
    (session_dir / "sess-aaaabbbb.jsonl").write_text(
        "\n".join(_transcript_lines()) + "\n", encoding="utf-8")
    return repo, projects


# ── exactness: the Loop 1 exit gate ───────────────────────────────────

def test_known_transcript_reproduces_the_exact_tally(tmp_path):
    repo, projects = _fixture(tmp_path)
    report = cost.measure(repo, projects_root=projects)
    assert report["available"] is True
    session = report["sessions"][0]
    assert session["steps"] == 2, "only records carrying usage are billed steps"
    assert session["input"] == 15
    assert session["output"] == 300
    assert session["cache_read"] == 3000
    assert session["cache_write"] == 50
    assert session["total_input"] == 3065          # 15 + 3000 + 50
    assert session["cost_per_step"] == 1532.5      # 3065 / 2
    assert session["tool_calls"] == 2, "an unbilled tool call still counts"
    assert session["tools"] == {"Bash": 1, "Read": 1}
    assert session["text_only_steps"] == 1, "the billed step with no tool call"
    assert session["tool_result_bytes"] == _EXPECTED_RESULT_BYTES
    assert session["first_timestamp"] == "2026-07-01T00:00:00Z"
    assert session["last_timestamp"] == "2026-07-01T00:05:00Z"


def test_totals_aggregate_across_sessions(tmp_path):
    repo, projects = _fixture(tmp_path)
    session_dir = cost.transcript_dir_for(repo, projects)
    (session_dir / "sess-ccccdddd.jsonl").write_text(
        "\n".join(_transcript_lines()) + "\n", encoding="utf-8")
    totals = cost.measure(repo, projects_root=projects)["totals"]
    assert totals["sessions"] == 2
    assert totals["steps"] == 4
    assert totals["total_input"] == 6130
    assert totals["cost_per_step"] == 1532.5
    assert totals["tool_result_tokens_approx"] == (2 * _EXPECTED_RESULT_BYTES) // 4


def test_a_torn_line_does_not_lose_the_session(tmp_path):
    """The fixture carries an unparseable line; the surrounding records must
    still be tallied rather than the whole session being dropped."""
    repo, projects = _fixture(tmp_path)
    assert cost.measure(repo, projects_root=projects)["sessions"][0]["steps"] == 2


# ── content-blindness (I1) and its anti-case ──────────────────────────

def test_no_planted_content_reaches_the_report(tmp_path):
    repo, projects = _fixture(tmp_path)
    dumped = json.dumps(cost.measure(repo, projects_root=projects))
    for canary in (CANARY_TOOL_INPUT, CANARY_ASSISTANT_TEXT,
                   CANARY_TOOL_RESULT, PLANTED_PATH):
        assert canary not in dumped, f"content leaked into the report: {canary}"
    # Anti-vacuous: the tool NAMES did come through, so the extractor really
    # walked the same blocks whose inputs it declined to read.
    assert "Bash" in dumped and "Read" in dumped


def test_the_leak_scanner_has_teeth():
    """If the scanner matched nothing, the test above would pass on a broken
    implementation. Prove it fires."""
    assert cost.scan_forbidden("see C:\\Users\\bob\\x") == ["windows_abs_path"]
    assert cost.scan_forbidden("see /home/bob/x") == ["unix_home_path"]
    assert cost.scan_forbidden(PLANTED_PATH) == ["unix_home_path"]
    assert cost.scan_forbidden("steps=401 total=102539053") == []


def test_record_refuses_to_write_when_the_payload_carries_a_path(tmp_path):
    """I3, fail closed: a leak must abort the write, not be filtered out of it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    poisoned = {"repo": "C:/Users/nobody/repo", "totals": {"steps": 1},
                "sessions": []}
    try:
        cost.record(repo, poisoned)
        raise AssertionError("record() wrote a payload containing an absolute path")
    except ValueError as exc:
        assert "windows_abs_path" in str(exc)
    assert not (repo / ".observatory" / "cost-history.jsonl").exists(), \
        "a refused write must leave no partial ledger entry"


def test_record_appends_a_clean_ledger_entry(tmp_path):
    repo, projects = _fixture(tmp_path)
    report = cost.measure(repo, projects_root=projects)
    path = cost.record(repo, report)
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["schema"] == cost.COST_SCHEMA
    assert entry["totals"]["steps"] == 2
    assert entry["sessions"] == 1


# ── three-state (I2): absence is not zero ─────────────────────────────

def test_absent_transcripts_report_unavailable_never_zero(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    report = cost.measure(repo, projects_root=tmp_path / "nothing-here")
    assert report["available"] is False
    assert report["reason"], "an unavailable report must say why"
    assert report["totals"] == {}, (
        "absence must not render as zeroed totals — a 0 here reads as 'cheap'")


def test_empty_transcript_dir_is_unavailable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    projects = tmp_path / "projects"
    cost.transcript_dir_for(repo, projects).mkdir(parents=True)
    assert cost.measure(repo, projects_root=projects)["available"] is False


def test_a_session_with_no_billed_step_has_no_cost_per_step(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    projects = tmp_path / "projects"
    session_dir = cost.transcript_dir_for(repo, projects)
    session_dir.mkdir(parents=True)
    (session_dir / "sess-empty.jsonl").write_text(
        json.dumps({"type": "assistant",
                    "message": {"role": "assistant", "content": []}}) + "\n",
        encoding="utf-8")
    session = cost.measure(repo, projects_root=projects)["sessions"][0]
    assert session["steps"] == 0
    assert session["cost_per_step"] is None, (
        "no billed step means no cost-per-step; 0.0 would be a made-up number")


def test_transcript_slug_matches_the_claude_layout(tmp_path):
    """Every non-alphanumeric character becomes a dash — including the
    underscore in a name like KP_SDLC."""
    repo = tmp_path / "KP_SDLC"
    repo.mkdir()
    name = cost.transcript_dir_for(repo, tmp_path / "projects").name
    assert name.endswith("KP-SDLC"), name
    assert set(name) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"), name


# ── CLI wiring ────────────────────────────────────────────────────────

def test_cli_cost_is_wired_and_emits_parseable_json(tmp_path, capsys):
    repo, projects = _fixture(tmp_path)
    rc = main(["--root", str(repo), "cost", "--json",
               "--projects-root", str(projects)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == cost.COST_SCHEMA
    assert payload["totals"]["steps"] == 2


def test_cli_exits_two_when_cost_cannot_be_measured(tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    rc = main(["--root", str(repo), "cost",
               "--projects-root", str(tmp_path / "absent")])
    assert rc == 2, "an unmeasurable repo must not exit 0"
    assert "UNAVAILABLE" in capsys.readouterr().out
