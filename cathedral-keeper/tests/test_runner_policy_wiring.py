"""Runner wiring tests for CK-DATA-SCHEMA-DRIFT and CK-AGENTIC-HARNESS.

These two policies are fully implemented but were never invoked by
``runner._run_policies`` (dead code). These integration tests drive the
runner directly and prove the policies fire when enabled and stay silent
when disabled — the gap no unit test of the policy functions can catch.

TDD: written before the wiring exists. Before the fix, the "enabled →
fires" tests FAIL (the runner returns zero findings); the "disabled →
silent" tests pass (conservation: default behaviour is unchanged).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.config import CKConfig
from cathedral_keeper.runner import _run_policies


# ── helpers ───────────────────────────────────────────────────────────

def _cfg(root: Path, policies: dict) -> CKConfig:
    raw = {
        "paths": {"include": [], "exclude": [], "extensions": [".py"]},
        "policies": policies,
        "python_roots": [],
    }
    return CKConfig(root=root.resolve(), raw=raw)


_AGENTIC_SRC = """\
class CustomerAgent:
    def invoke(self, query):
        return self.handle(query)

    def handle(self, query):
        return {"answer": query}
"""

_MODEL_V1 = """\
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str
    name: str
"""

_MODEL_V2_REMOVED_FIELD = """\
from pydantic import BaseModel


class User(BaseModel):
    id: int
    email: str
"""


def _write(root: Path, rel: str, content: str) -> Path:
    p = (root / rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p.resolve()


def _ids(findings, policy_id):
    return [f for f in findings if f.policy_id == policy_id]


# ── CK-AGENTIC-HARNESS wiring ─────────────────────────────────────────

def test_runner_fires_agentic_harness_when_enabled():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = _write(root, "agent.py", _AGENTIC_SRC)
        cfg = _cfg(root, {"CK-AGENTIC-HARNESS": {"enabled": True, "config": {}}})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        hits = _ids(findings, "CK-AGENTIC-HARNESS")
        assert len(hits) >= 1, f"expected CK-AGENTIC-HARNESS findings, got {len(hits)}"


def test_runner_silent_agentic_harness_when_disabled():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = _write(root, "agent.py", _AGENTIC_SRC)
        cfg = _cfg(root, {"CK-AGENTIC-HARNESS": {"enabled": False, "config": {}}})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        assert _ids(findings, "CK-AGENTIC-HARNESS") == []


# ── CK-DATA-SCHEMA-DRIFT wiring ───────────────────────────────────────

def _write_schema_baseline(root: Path) -> None:
    """Write a baseline snapshot containing the v1 User model."""
    baseline = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "commit": "testbase",
        "metrics": {},
        "schemas": {
            "models.py": {
                "User": {
                    "fields": {
                        "id": {"type": "int", "has_default": False},
                        "email": {"type": "str", "has_default": False},
                        "name": {"type": "str", "has_default": False},
                    }
                }
            }
        },
    }
    bp = root / ".quality-reports" / "cathedral-keeper" / "baseline.json"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(baseline, indent=2), encoding="utf-8")


def test_runner_fires_schema_drift_on_removed_field():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_schema_baseline(root)
        # current state: User lost its `name` field
        f = _write(root, "models.py", _MODEL_V2_REMOVED_FIELD)
        cfg = _cfg(root, {"CK-DATA-SCHEMA-DRIFT": {
            "enabled": True,
            "config": {"baseline_path": ".quality-reports/cathedral-keeper/baseline.json"},
        }})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        hits = _ids(findings, "CK-DATA-SCHEMA-DRIFT")
        assert len(hits) >= 1, f"expected schema-drift findings, got {len(hits)}"
        removed = [h for h in hits if "name" in h.title and "removed" in h.title.lower()]
        assert removed, f"expected a 'name removed' finding, got {[h.title for h in hits]}"
        assert removed[0].severity == "high"


def test_runner_schema_drift_info_when_no_baseline():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        f = _write(root, "models.py", _MODEL_V1)
        cfg = _cfg(root, {"CK-DATA-SCHEMA-DRIFT": {
            "enabled": True,
            "config": {"baseline_path": ".quality-reports/cathedral-keeper/baseline.json"},
        }})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        hits = _ids(findings, "CK-DATA-SCHEMA-DRIFT")
        assert len(hits) == 1, f"expected one info finding, got {len(hits)}"
        assert hits[0].severity == "info"
        assert hits[0].metadata.get("status") == "no_baseline"


def test_runner_silent_schema_drift_when_disabled():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_schema_baseline(root)
        f = _write(root, "models.py", _MODEL_V2_REMOVED_FIELD)
        cfg = _cfg(root, {"CK-DATA-SCHEMA-DRIFT": {"enabled": False, "config": {}}})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        assert _ids(findings, "CK-DATA-SCHEMA-DRIFT") == []


_MODEL_CONFIG_A = """\
from pydantic import BaseModel


class Config(BaseModel):
    a: int
"""

_MODEL_CONFIG_B = """\
from pydantic import BaseModel


class Config(BaseModel):
    b: str
"""


def _write_dupname_baseline(root: Path) -> None:
    """Baseline with TWO files each defining a `Config` model (common name)."""
    baseline = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "commit": "testbase",
        "metrics": {},
        "schemas": {
            "a.py": {"Config": {"fields": {"a": {"type": "int", "has_default": False}}}},
            "b.py": {"Config": {"fields": {"b": {"type": "str", "has_default": False}}}},
        },
    }
    bp = root / ".quality-reports" / "cathedral-keeper" / "baseline.json"
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_text(json.dumps(baseline, indent=2), encoding="utf-8")


def test_runner_schema_drift_no_false_positive_on_duplicate_model_names():
    """Same-named models in different files, UNCHANGED content, must not drift.

    Regression for the order-dependent collision in name-keyed merging:
    passing files in a different order than the baseline must not fabricate
    'removed'/'added' findings when nothing actually changed.
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _write_dupname_baseline(root)
        fa = _write(root, "a.py", _MODEL_CONFIG_A)
        fb = _write(root, "b.py", _MODEL_CONFIG_B)
        cfg = _cfg(root, {"CK-DATA-SCHEMA-DRIFT": {
            "enabled": True,
            "config": {"baseline_path": ".quality-reports/cathedral-keeper/baseline.json"},
        }})
        # Reversed order relative to the baseline — trips name-merge collisions.
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[fb, fa])
        hits = _ids(findings, "CK-DATA-SCHEMA-DRIFT")
        assert hits == [], f"unchanged dup-named models drifted: {[h.title for h in hits]}"


def test_runner_schema_drift_distinguishes_corrupt_baseline():
    """A malformed baseline file is not reported as a missing one."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        bp = root / ".quality-reports" / "cathedral-keeper" / "baseline.json"
        bp.parent.mkdir(parents=True, exist_ok=True)
        bp.write_text("{ this is not valid json", encoding="utf-8")
        f = _write(root, "models.py", _MODEL_V1)
        cfg = _cfg(root, {"CK-DATA-SCHEMA-DRIFT": {
            "enabled": True,
            "config": {"baseline_path": ".quality-reports/cathedral-keeper/baseline.json"},
        }})
        findings = _run_policies(root=root.resolve(), cfg=cfg, files=[f])
        hits = _ids(findings, "CK-DATA-SCHEMA-DRIFT")
        assert len(hits) == 1
        assert hits[0].metadata.get("status") == "baseline_unreadable", \
            f"corrupt baseline should be distinct from no_baseline, got {hits[0].metadata}"


# ── Runner ────────────────────────────────────────────────────────────

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
