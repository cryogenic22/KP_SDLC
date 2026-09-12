"""The engine must dogfood the cross-agent contract it ships."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
START = "<!-- kp-sdlc:common-agent-contract:v1 -->"
END = "<!-- /kp-sdlc:common-agent-contract:v1 -->"


def _contract(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.find(START)
    end = text.find(END)
    assert start >= 0 and end > start, f"{path.name} has no complete agent contract"
    return text[start:end + len(END)]


def test_root_agent_contract_is_identical_for_claude_and_codex():
    agents = _contract(ROOT / "AGENTS.md")
    claude = _contract(ROOT / "CLAUDE.md")
    assert agents == claude, "AGENTS.md and CLAUDE.md give agents different rules"


def test_contract_pins_independent_merge_and_non_vacuous_evidence():
    contract = _contract(ROOT / "AGENTS.md")
    required = (
        "Implementation agents",
        "independent reviewer owns the merge decision",
        "exact SHA",
        "positive control",
        "planted failing case",
        "fewer avoidable review rounds",
        "Reproduce a novel issue",
        "earliest-prevention action",
        "/close-review-loop",
        "CtxPack ledger recall",
    )
    missing = [phrase for phrase in required if phrase not in contract]
    assert not missing, f"agent contract lost required invariants: {missing}"


def test_both_agent_instruction_files_are_protected():
    surface = (ROOT / "protected-surface.txt").read_text(encoding="utf-8")
    stripped = (line.strip() for line in surface.splitlines())
    entries = {line for line in stripped if line and not line.startswith("#")}
    assert {"AGENTS.md", "CLAUDE.md"} <= entries


def test_review_learning_policy_is_protected():
    surface = (ROOT / "protected-surface.txt").read_text(encoding="utf-8")
    entries = {
        line.strip()
        for line in surface.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    required = {
        ".github/PULL_REQUEST_TEMPLATE.md",
        "harness/process/",
        "harness/commands/",
        "harness/skills/",
        "harness/templates/PULL_REQUEST_TEMPLATE.md.tmpl",
    }
    assert required <= entries, f"review policy lost protected paths: {required - entries}"
