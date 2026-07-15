"""Contract for the CTX dogfood baseline generator (eval_engine.ctx_baseline).

Standalone: ``python -m pytest eval-engine/tests/ -q``. Four properties, each with
an anti-case so the guard cannot silently rot:

* torn-read safety — a ledger that changes mid-capture is DETECTED (torn) and
  fails closed; a stable ledger captures in one attempt;
* privacy — the manifest is born sanitized (no abs paths, session UUIDs, or raw
  commands), and the enforced scanner is NOT vacuous (it fires on a planted leak);
* runtime + config provenance — the manifest pins the ctxpack runtime and, per
  repo, the hook/MCP launch hashes and which servers set PYTHONPATH (the
  Market-Zero-vs-Transmax signal);
* schema validation — a well-formed manifest validates; a tampered one is caught
  (missing key / wrong type / wrong const), so the validator has teeth.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval-engine"))
sys.path.insert(0, str(ROOT / "schemas"))  # eval_engine.__init__ imports sdlc_schemas

from eval_engine import ctx_baseline as cb  # noqa: E402

_FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_UUID = "123e4567-e89b-12d3-a456-426614174000"
_LEAKY_HOOK = "python C:/Users/secretperson/.harness/hooks/x.py"


def _make_repo(root: Path, *, mcp: dict | None = None) -> Path:
    """A fake repo tree with a ledger, a UUID-named session artifact, a hook whose
    command embeds an absolute path, and an optional .mcp.json."""
    ctx = root / ".claude" / "ctx"
    ctx.mkdir(parents=True)
    (ctx / "checkpoints.jsonl").write_bytes(b'{"session":"s1","kind":"checkpoint"}\n')
    (ctx / "events.jsonl").write_bytes(b'{"e":1}\n{"e":2}\n')
    (ctx / f"session-{_UUID}.ctx").write_bytes(b"PACK-BODY-should-never-appear-verbatim\n")
    settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": _LEAKY_HOOK}]}]}}
    (root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    if mcp is not None:
        (root / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")
    return root


def _benign_stats(_frozen):
    return {"sessions": 1, "checkpoints": 1, "captured": {"decisions": 3}}


# ── torn-read safety ─────────────────────────────────────────────────

def test_torn_read_detected_and_stable_read_clean(tmp_path):
    repo = _make_repo(tmp_path / "r")
    ctx = repo / ".claude" / "ctx"

    # Stable ledger: no mutation during capture -> not torn, single attempt.
    clean = cb.capture_ledger(ctx, attempts=3, stats_fn=_benign_stats)
    assert clean["torn"] is False and clean["capture_attempts"] == 1

    # Concurrent write: stats_fn mutates the LIVE ledger every call, so the
    # after-hash never matches the before-hash -> torn after the retry budget.
    calls = {"n": 0}

    def mutating(_frozen):
        calls["n"] += 1
        (ctx / "checkpoints.jsonl").write_bytes(f'{{"mutated":{calls["n"]}}}\n'.encode())
        return {"sessions": 1}

    torn = cb.capture_ledger(ctx, attempts=3, stats_fn=mutating)
    assert torn["torn"] is True, "a ledger changing mid-capture must be marked torn"
    assert torn["capture_attempts"] == 3, "torn capture must exhaust the retry budget"
    assert calls["n"] == 3


# ── privacy ──────────────────────────────────────────────────────────

def test_manifest_born_sanitized_and_scanner_has_teeth(tmp_path):
    repo = _make_repo(tmp_path / "r")
    manifest = cb.build_manifest([{"label": "repo-a", "path": str(repo)}],
                                 now=_FIXED_NOW, stats_fn=_benign_stats)
    blob = json.dumps(manifest)

    # Nothing sensitive leaks: not the abs repo path, the session UUID, the pack
    # body, or the raw hook command (with its embedded path + username).
    assert str(repo) not in blob, "absolute repo path leaked into the manifest"
    assert _UUID not in blob, "session UUID leaked into the manifest"
    assert "secretperson" not in blob and ".harness/hooks/x.py" not in blob, "raw hook command leaked"
    assert "PACK-BODY" not in blob, "session artifact content leaked"

    # The enforced scanner passes on real output...
    assert cb.scan_forbidden(blob) == []
    # ...but is NOT vacuous: it fires on a planted abs path AND a planted UUID.
    planted = blob + ' "/Users/leak/secret.txt" ' + _UUID
    hits = cb.scan_forbidden(planted)
    assert any("unix_home_path" in h for h in hits)
    assert any("session_uuid" in h for h in hits)

    # The opaque artifact id is used instead of the UUID filename.
    arts = manifest["repos"][0]["ledger"]["session_artifacts"]
    assert arts and arts[0]["id"] == "artifact-1" and len(arts[0]["sha256"]) == 64


# ── runtime + config provenance ──────────────────────────────────────

def test_runtime_and_config_provenance_captured(tmp_path):
    mcp = {"mcpServers": {
        "ctxpack": {"command": "python", "args": ["-m", "ctxpack.integrations.mcp_server"]},
        "ctxpack-code": {"command": "python", "args": ["-m", "ctxpack.integrations.mcp_code"],
                         "env": {"PYTHONPATH": "/private/engine/src"}},
    }}
    repo = _make_repo(tmp_path / "r", mcp=mcp)
    manifest = cb.build_manifest([{"label": "repo-a", "path": str(repo)}],
                                 now=_FIXED_NOW, stats_fn=_benign_stats)

    rt = manifest["ctx_runtime"]
    assert len(rt["python_executable_sha256"]) == 64
    assert rt["python_version"]
    assert set(rt["ctxpack"]) >= {"module_path_sha256", "source_sha256", "version"}

    cfg = manifest["repos"][0]["config"]
    assert cfg["hook_commands_sha256"] and all(len(h) == 64 for h in cfg["hook_commands_sha256"])
    assert cfg["mcp_servers"] == ["ctxpack", "ctxpack-code"]
    # The Market-Zero-vs-Transmax signal: the extra server's PYTHONPATH is flagged,
    # and its value ("/private/engine/src") is NOT stored (only a boolean + hash).
    assert cfg["mcp_sets_pythonpath"] == {"ctxpack": False, "ctxpack-code": True}
    assert "/private/engine/src" not in json.dumps(manifest)


# ── schema validation ────────────────────────────────────────────────

def test_schema_validation_has_teeth(tmp_path):
    repo = _make_repo(tmp_path / "r")
    manifest = cb.build_manifest([{"label": "repo-a", "path": str(repo)}],
                                 now=_FIXED_NOW, stats_fn=_benign_stats)
    schema = cb.load_schema()
    assert cb.validate_manifest(manifest, schema) == [], "a well-formed manifest must validate"

    # (a) missing required top-level key
    m1 = {k: v for k, v in manifest.items() if k != "repos"}
    assert any("repos" in e for e in cb.validate_manifest(m1, schema))
    # (b) wrong const on the schema tag
    m2 = dict(manifest, schema="ctx-dogfood-baseline/manifest@999")
    assert any("const" in e for e in cb.validate_manifest(m2, schema))
    # (c) wrong type deep in a repo entry
    import copy
    m3 = copy.deepcopy(manifest)
    m3["repos"][0]["ledger"]["torn"] = "nope"
    assert any("torn" in e for e in cb.validate_manifest(m3, schema))


# ── split dirty ──────────────────────────────────────────────────────

def test_classify_separates_code_ledger_config():
    assert cb._classify(".claude/ctx/checkpoints.jsonl") == "ledger"
    assert cb._classify(".claude/settings.json") == "config"
    assert cb._classify(".mcp.json") == "config"
    assert cb._classify("eval-engine/eval_engine/ctx_baseline.py") == "code"
    assert cb._classify(".claude\\ctx\\events.jsonl") == "ledger"  # windows sep


def test_split_dirty_flags_are_independent(tmp_path):
    if not shutil.which("git"):
        import pytest
        pytest.skip("git not available")
    repo = tmp_path / "gitrepo"
    (repo / ".claude" / "ctx").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    # only a ledger change -> ledger_dirty True, code/config False
    (repo / ".claude" / "ctx" / "checkpoints.jsonl").write_text("{}\n", encoding="utf-8")
    d = cb._split_dirty(str(repo))
    assert d["ledger_dirty"] is True
    assert d["code_worktree_dirty"] is False and d["config_dirty"] is False
    # add a code file + a config file -> all three independent flags set
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    d2 = cb._split_dirty(str(repo))
    assert d2["code_worktree_dirty"] and d2["ledger_dirty"] and d2["config_dirty"]
    assert len(d2["non_ledger_diff_sha256"]) == 64
