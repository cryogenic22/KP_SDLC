"""Phase 4 — Tests for TESTED_BY edge detection.

TDD: Defines the contract for analyzing test file imports to
create TESTED_BY edges and flag untested source files.

Test graph:
    tests/test_auth.py → src/auth.py (TESTED_BY)
    tests/test_auth.py → src/models.py (TESTED_BY)
    tests/test_db.py → src/db.py (TESTED_BY)
    src/utils.py — no test imports it (UNTESTED)
    src/__init__.py — excluded by default
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.python_graph import ImportEdge, PyGraph


def _build_test_graph() -> PyGraph:
    """Build a graph with test→source imports."""
    edges = [
        # Production code imports
        ImportEdge(src_file="src/auth.py", dst_file="src/models.py", module="src.models", line=1),
        ImportEdge(src_file="src/auth.py", dst_file="src/db.py", module="src.db", line=2),
        ImportEdge(src_file="src/db.py", dst_file="src/utils.py", module="src.utils", line=1),
        # Test imports (these create TESTED_BY edges)
        ImportEdge(src_file="tests/test_auth.py", dst_file="src/auth.py", module="src.auth", line=1),
        ImportEdge(src_file="tests/test_auth.py", dst_file="src/models.py", module="src.models", line=2),
        ImportEdge(src_file="tests/test_db.py", dst_file="src/db.py", module="src.db", line=1),
        # Test helper import (not a source file test)
        ImportEdge(src_file="tests/test_auth.py", dst_file="tests/conftest.py", module="tests.conftest", line=3),
    ]
    module_index = {
        "src.auth": "src/auth.py",
        "src.models": "src/models.py",
        "src.db": "src/db.py",
        "src.utils": "src/utils.py",
        "src": "src/__init__.py",
        "tests.test_auth": "tests/test_auth.py",
        "tests.test_db": "tests/test_db.py",
        "tests.conftest": "tests/conftest.py",
    }
    return PyGraph(module_index=module_index, edges=edges)


# ── Import module under test ─────────────────────────────────────────

from cathedral_keeper.policies.test_coverage import detect_test_edges, check_test_coverage
from cathedral_keeper.models import Finding


# ── detect_test_edges tests ──────────────────────────────────────────


def test_detect_test_edges_basic():
    """Should map source files to test files that import them."""
    graph = _build_test_graph()
    edges = detect_test_edges(graph)

    # src/auth.py is tested by tests/test_auth.py
    assert "tests/test_auth.py" in edges.get("src/auth.py", [])
    # src/models.py is tested by tests/test_auth.py
    assert "tests/test_auth.py" in edges.get("src/models.py", [])
    # src/db.py is tested by tests/test_db.py
    assert "tests/test_db.py" in edges.get("src/db.py", [])


def test_detect_test_edges_untested_file():
    """src/utils.py has no test importing it — should not appear."""
    graph = _build_test_graph()
    edges = detect_test_edges(graph)

    assert "src/utils.py" not in edges


def test_detect_test_edges_excludes_test_to_test():
    """Test importing conftest should not create a TESTED_BY edge for conftest."""
    graph = _build_test_graph()
    edges = detect_test_edges(graph)

    # conftest.py is not "tested" by test_auth.py — it's a helper
    assert "tests/conftest.py" not in edges


def test_detect_test_edges_excludes_init():
    """__init__.py should not appear in TESTED_BY mapping."""
    graph = _build_test_graph()
    edges = detect_test_edges(graph)

    assert "src/__init__.py" not in edges


# ── check_test_coverage tests ────────────────────────────────────────


def test_check_test_coverage_flags_untested():
    """Source files with zero test coverage should produce findings."""
    graph = _build_test_graph()
    source_files = ["src/auth.py", "src/models.py", "src/db.py", "src/utils.py"]

    findings = check_test_coverage(
        graph=graph,
        source_files=source_files,
        cfg={"severity": "low"},
    )

    untested_files = [f.evidence[0].file for f in findings]
    assert "src/utils.py" in untested_files


def test_check_test_coverage_passes_tested():
    """Tested source files should NOT produce findings."""
    graph = _build_test_graph()
    source_files = ["src/auth.py", "src/models.py", "src/db.py", "src/utils.py"]

    findings = check_test_coverage(
        graph=graph,
        source_files=source_files,
        cfg={"severity": "low"},
    )

    flagged_files = {f.evidence[0].file for f in findings}
    assert "src/auth.py" not in flagged_files
    assert "src/db.py" not in flagged_files


def test_check_test_coverage_excludes_patterns():
    """Files matching exclude patterns should be skipped."""
    graph = _build_test_graph()
    source_files = ["src/auth.py", "src/utils.py"]

    findings = check_test_coverage(
        graph=graph,
        source_files=source_files,
        cfg={"severity": "low", "exclude_patterns": ["**/utils.py"]},
    )

    flagged_files = {f.evidence[0].file for f in findings}
    assert "src/utils.py" not in flagged_files


def test_check_test_coverage_correct_policy_id():
    """Findings should use CK-ARCH-TEST-COVERAGE policy ID."""
    graph = _build_test_graph()
    findings = check_test_coverage(
        graph=graph,
        source_files=["src/utils.py"],
        cfg={"severity": "low"},
    )

    for f in findings:
        assert f.policy_id == "CK-ARCH-TEST-COVERAGE"


def test_check_test_coverage_configurable_severity():
    """Severity should come from config."""
    graph = _build_test_graph()
    findings = check_test_coverage(
        graph=graph,
        source_files=["src/utils.py"],
        cfg={"severity": "medium"},
    )

    assert all(f.severity == "medium" for f in findings)


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
