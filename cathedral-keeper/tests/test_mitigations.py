"""S6 — Tests for mitigation detection.

Team Feedback #7: CK narrative says "freeze feature development"
without checking if repo already has quality gates, ratchet systems,
or CI pipelines that already prevent regression.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.mitigations import detect_mitigations, Mitigations


# ── Helpers ──────────────────────────────────────────────────────────


def _make_repo(structure: dict[str, str]) -> Path:
    """Create a temp directory with given file structure."""
    tmp = tempfile.mkdtemp()
    for path, content in structure.items():
        full = os.path.join(tmp, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    return Path(tmp)


def _cleanup(path: Path):
    import shutil
    shutil.rmtree(str(path), ignore_errors=True)


# ── Detection Tests ──────────────────────────────────────────────────


def test_detects_ci_pipeline():
    """Should detect .github/workflows/ as CI pipeline."""
    root = _make_repo({".github/workflows/ci.yml": "name: CI"})
    m = detect_mitigations(root)
    assert m.has_ci is True
    _cleanup(root)


def test_detects_quality_gate():
    """Should detect quality-gate/ directory."""
    root = _make_repo({"quality-gate/quality_gate.py": "# QG"})
    m = detect_mitigations(root)
    assert m.has_quality_gate is True
    _cleanup(root)


def test_detects_ck_config():
    """Should detect .cathedral-keeper.json."""
    root = _make_repo({".cathedral-keeper.json": "{}"})
    m = detect_mitigations(root)
    assert m.has_ck_config is True
    _cleanup(root)


def test_detects_coverage_threshold():
    """Should detect coverage threshold in pyproject.toml."""
    root = _make_repo({"pyproject.toml": "[tool.pytest.ini_options]\n--cov-fail-under = 40"})
    m = detect_mitigations(root)
    assert m.has_coverage_threshold is True
    _cleanup(root)


def test_detects_pre_commit_hooks():
    """Should detect .pre-commit-config.yaml."""
    root = _make_repo({".pre-commit-config.yaml": "repos: []"})
    m = detect_mitigations(root)
    assert m.has_pre_commit is True
    _cleanup(root)


def test_empty_repo_no_mitigations():
    """Empty repo should have no mitigations."""
    root = _make_repo({"README.md": "# Hello"})
    m = detect_mitigations(root)
    assert m.has_ci is False
    assert m.has_quality_gate is False
    assert m.has_ck_config is False
    assert m.has_coverage_threshold is False
    assert m.has_pre_commit is False
    _cleanup(root)


def test_mitigation_count():
    """count property should reflect total mitigations found."""
    root = _make_repo({
        ".github/workflows/ci.yml": "name: CI",
        "quality-gate/qg.py": "# QG",
        ".cathedral-keeper.json": "{}",
    })
    m = detect_mitigations(root)
    assert m.count == 3
    _cleanup(root)


def test_narrative_tone_with_mitigations():
    """With mitigations, narrative tone should be 'incremental'."""
    root = _make_repo({
        ".github/workflows/ci.yml": "name: CI",
        "quality-gate/qg.py": "# QG",
    })
    m = detect_mitigations(root)
    assert m.narrative_tone == "incremental"
    _cleanup(root)


def test_narrative_tone_without_mitigations():
    """Without mitigations, narrative tone should be 'urgent'."""
    root = _make_repo({"README.md": "# Hello"})
    m = detect_mitigations(root)
    assert m.narrative_tone == "urgent"
    _cleanup(root)


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
