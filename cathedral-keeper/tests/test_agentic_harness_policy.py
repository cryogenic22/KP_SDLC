"""TDD spec for Agentic Harness Architecture Policy.

Verifies that the CK-AGENTIC-HARNESS policy correctly detects the
presence or absence of the 9 agentic infrastructure modules across
a codebase, and only fires for codebases that are actually agentic.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.policies.agentic_harness import (
    check_agentic_harness_policy,
    _is_agentic_codebase,
)

# ── Helpers ──────────────────────────────────────────────────────────

ROOT = Path("/fake/project")


def _make_files_and_contents(file_map: dict[str, str]):
    """Build (files, file_contents) from a {relative_path: source} dict."""
    files = [ROOT / p for p in file_map]
    file_contents = {str(ROOT / p): src for p, src in file_map.items()}
    return files, file_contents


def _run(file_map: dict[str, str]):
    files, contents = _make_files_and_contents(file_map)
    return check_agentic_harness_policy(root=ROOT, files=files, file_contents=contents)


# Minimal agentic source that triggers the gate but has no infra modules.
_BARE_AGENT = {"agent.py": "class MyAgent:\n    def invoke(self, tool_call):\n        pass\n"}


# ── Detection: missing modules ──────────────────────────────────────


def test_detects_missing_tool_registry():
    """A bare agentic codebase should produce a tool_registry finding."""
    findings = _run(_BARE_AGENT)
    registry_findings = [f for f in findings if f.metadata["module"] == "tool_registry"]
    assert len(registry_findings) == 1
    assert registry_findings[0].title == "No tool registry detected"


def test_detects_missing_permissions():
    """Permission system missing should be flagged."""
    findings = _run(_BARE_AGENT)
    perm = [f for f in findings if f.metadata["module"] == "permission_system"]
    assert len(perm) == 1
    assert "permission" in perm[0].title.lower()


def test_detects_missing_session_persistence():
    """Session persistence missing should be flagged."""
    findings = _run(_BARE_AGENT)
    sess = [f for f in findings if f.metadata["module"] == "session_persistence"]
    assert len(sess) == 1
    assert "session" in sess[0].title.lower()


# ── Detection: modules present ───────────────────────────────────────


def test_passes_when_registry_exists():
    """If a file contains ToolRegistry, no tool_registry finding."""
    src = {
        "agent.py": "class MyAgent:\n    def invoke(self): pass\n",
        "registry.py": "class ToolRegistry:\n    _REGISTRY = {}\n",
    }
    findings = _run(src)
    registry_findings = [f for f in findings if f.metadata["module"] == "tool_registry"]
    assert len(registry_findings) == 0


def test_passes_when_permissions_exist():
    """If a file contains TrustTier, no permission_system finding."""
    src = {
        "agent.py": "class MyAgent:\n    def invoke(self): pass\n",
        "perms.py": "class TrustTier:\n    SYSTEM = 'system'\n",
    }
    findings = _run(src)
    perm = [f for f in findings if f.metadata["module"] == "permission_system"]
    assert len(perm) == 0


# ── Severity ─────────────────────────────────────────────────────────


def test_severity_high_for_security_modules():
    """Permission system and session persistence should be HIGH severity."""
    findings = _run(_BARE_AGENT)
    perm = [f for f in findings if f.metadata["module"] == "permission_system"]
    sess = [f for f in findings if f.metadata["module"] == "session_persistence"]
    assert perm[0].severity == "high"
    assert sess[0].severity == "high"

    # Other modules should be medium
    others = [f for f in findings if f.metadata["module"] not in ("permission_system", "session_persistence")]
    for f in others:
        assert f.severity == "medium", f"Expected medium for {f.metadata['module']}, got {f.severity}"


# ── Finding structure ────────────────────────────────────────────────


def test_finding_has_fix_options():
    """Every finding must include non-empty fix_options."""
    findings = _run(_BARE_AGENT)
    assert len(findings) > 0
    for f in findings:
        assert len(f.fix_options) > 0, f"Finding {f.title} has no fix_options"
        assert all(isinstance(opt, str) and opt for opt in f.fix_options)


def test_finding_metadata_structure():
    """Each finding metadata must have module, found, searched_patterns."""
    findings = _run(_BARE_AGENT)
    for f in findings:
        assert "module" in f.metadata
        assert f.metadata["found"] is False
        assert "searched_patterns" in f.metadata
        assert isinstance(f.metadata["searched_patterns"], list)
        assert len(f.metadata["searched_patterns"]) > 0


def test_finding_policy_id():
    """All findings should use policy_id CK-AGENTIC-HARNESS."""
    findings = _run(_BARE_AGENT)
    for f in findings:
        assert f.policy_id == "CK-AGENTIC-HARNESS"


# ── Agentic gate ─────────────────────────────────────────────────────


def test_non_agent_codebase_minimal_findings():
    """A plain CRUD app with no agent patterns should produce zero findings."""
    crud_src = {
        "app.py": "from flask import Flask\napp = Flask(__name__)\n",
        "models.py": "class User:\n    name: str\n",
        "views.py": "def index():\n    return 'hello'\n",
    }
    findings = _run(crud_src)
    assert len(findings) == 0


def test_is_agentic_codebase_true():
    """Codebase with 'agent' keyword should be detected as agentic."""
    assert _is_agentic_codebase({"a.py": "class MyAgent:\n    pass"}) is True


def test_is_agentic_codebase_false():
    """Codebase without any agent-related keywords should not be agentic."""
    assert _is_agentic_codebase({"a.py": "print('hello')"}) is False


# ── All 9 modules present ───────────────────────────────────────────


def test_all_modules_present_no_findings():
    """When all 9 infra modules exist, zero findings should be emitted."""
    src = {
        "agent.py": "class MyAgent:\n    def invoke(self): pass\n",
        "registry.py": "class ToolRegistry:\n    pass\n",
        "perms.py": "class TrustTier:\n    pass\ndef authorize(): pass\n",
        "session.py": "class SessionStore:\n    def checkpoint(self): pass\n",
        "state.py": "class WorkflowState:\n    pass\ndef build_turn_context(): pass\n",
        "budget.py": "class TokenBudget:\n    def estimate_tokens(self): pass\n",
        "events.py": "class EventStream:\n    def emit_event(self): pass\n",
        "verify.py": "class Verifier:\n    def verify(self): pass\n",
        "types.py": "class Orchestrator:\n    pass\nclass Executor:\n    pass\n",
        "harness.py": "class AgentHarness:\n    def run(self): pass\n",
    }
    findings = _run(src)
    assert len(findings) == 0


# ── Evidence ─────────────────────────────────────────────────────────


def test_evidence_lists_scanned_files():
    """Evidence should reference the files that were scanned."""
    findings = _run(_BARE_AGENT)
    assert len(findings) > 0
    for f in findings:
        assert len(f.evidence) > 0
        for e in f.evidence:
            assert "Scanned for" in e.note


# ── Runner ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
