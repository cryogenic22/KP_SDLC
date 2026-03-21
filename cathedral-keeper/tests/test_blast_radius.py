"""Phase 2 — Tests for blast-radius analysis.

TDD: Defines the contract for reverse-edge BFS, fan-in scoring,
and affected-test detection.

Test graph topology:
    a.py → b.py → c.py → d.py
                ↘ e.py
    test_b.py → b.py
    test_c.py → c.py
    f.py → g.py → f.py  (cycle)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.python_graph import ImportEdge, PyGraph


def _build_test_graph() -> PyGraph:
    """Build the test graph topology documented above."""
    edges = [
        ImportEdge(src_file="a.py", dst_file="b.py", module="b", line=1),
        ImportEdge(src_file="b.py", dst_file="c.py", module="c", line=1),
        ImportEdge(src_file="c.py", dst_file="d.py", module="d", line=1),
        ImportEdge(src_file="c.py", dst_file="e.py", module="e", line=2),
        ImportEdge(src_file="tests/test_b.py", dst_file="b.py", module="b", line=1),
        ImportEdge(src_file="tests/test_c.py", dst_file="c.py", module="c", line=1),
        # Cycle
        ImportEdge(src_file="f.py", dst_file="g.py", module="g", line=1),
        ImportEdge(src_file="g.py", dst_file="f.py", module="f", line=1),
    ]
    return PyGraph(module_index={}, edges=edges)


# ── Import module under test ─────────────────────────────────────────

from cathedral_keeper.blast_radius import (
    BlastRadius,
    build_reverse_index,
    compute_blast_radius,
    identify_high_fan_in,
)


# ── build_reverse_index tests ────────────────────────────────────────


def test_reverse_index_structure():
    """Reverse index should map dst_file → list of src_files that import it."""
    graph = _build_test_graph()
    rev = build_reverse_index(graph)

    # b.py is imported by a.py and tests/test_b.py
    assert set(rev["b.py"]) == {"a.py", "tests/test_b.py"}
    # c.py is imported by b.py and tests/test_c.py
    assert set(rev["c.py"]) == {"b.py", "tests/test_c.py"}
    # d.py is imported by c.py only
    assert rev["d.py"] == ["c.py"]


def test_reverse_index_cycle():
    """Reverse index should handle cycles without duplication."""
    graph = _build_test_graph()
    rev = build_reverse_index(graph)

    assert "g.py" in rev["f.py"]  # g imports f
    assert "f.py" in rev["g.py"]  # f imports g


def test_reverse_index_no_importers():
    """Files that nobody imports should not appear in reverse index."""
    graph = _build_test_graph()
    rev = build_reverse_index(graph)

    # a.py is not imported by anything
    assert "a.py" not in rev


# ── compute_blast_radius tests ───────────────────────────────────────


def test_blast_radius_direct_dependents():
    """Changing c.py: direct dependents are b.py and tests/test_c.py."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"])

    assert "b.py" in br.direct_dependents
    assert "tests/test_c.py" in br.direct_dependents
    # d.py and e.py are imported BY c.py, not importers OF c.py
    assert "d.py" not in br.direct_dependents
    assert "e.py" not in br.direct_dependents


def test_blast_radius_transitive_dependents():
    """Changing c.py: transitive dependents include a.py (imports b.py which imports c.py)."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"], max_depth=3)

    # a.py → b.py → c.py: a.py is a transitive dependent of c.py
    assert "a.py" in br.transitive_dependents


def test_blast_radius_includes_test_files():
    """Affected tests should be identified from the dependent set."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"], include_tests=True)

    assert "tests/test_c.py" in br.affected_tests
    # test_b.py imports b.py which imports c.py — should be caught transitively
    assert "tests/test_b.py" in br.affected_tests


def test_blast_radius_respects_max_depth():
    """max_depth=1 should only find direct dependents."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"], max_depth=1)

    assert "b.py" in br.direct_dependents
    # a.py is 2 hops away — should NOT be in transitive when max_depth=1
    assert "a.py" not in br.transitive_dependents


def test_blast_radius_handles_cycles():
    """BFS on cyclic graph should terminate and not loop infinitely."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["f.py"], max_depth=10)

    # g.py imports f.py, so g.py is a direct dependent
    assert "g.py" in br.direct_dependents
    # Should terminate — not hang or raise
    assert isinstance(br, BlastRadius)


def test_blast_radius_changed_files_in_output():
    """Changed files should be recorded in the result."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py", "d.py"])

    assert "c.py" in br.changed_files
    assert "d.py" in br.changed_files


def test_blast_radius_no_tests_flag():
    """include_tests=False should exclude test files from affected_tests."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"], include_tests=False)

    assert len(br.affected_tests) == 0


def test_blast_radius_fan_in_scores():
    """fan_in_scores should count incoming edges per file."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, ["c.py"])

    # b.py has 2 importers: a.py and tests/test_b.py
    assert br.fan_in_scores.get("b.py", 0) == 2
    # c.py has 2 importers: b.py and tests/test_c.py
    assert br.fan_in_scores.get("c.py", 0) == 2


def test_blast_radius_empty_changed_files():
    """Empty changed files should produce empty blast radius."""
    graph = _build_test_graph()
    br = compute_blast_radius(graph, [])

    assert br.direct_dependents == []
    assert br.transitive_dependents == []
    assert br.affected_tests == []


# ── identify_high_fan_in tests ───────────────────────────────────────


def test_high_fan_in_identifies_hotspots():
    """Files with fan-in >= threshold should be returned."""
    graph = _build_test_graph()
    hotspots = identify_high_fan_in(graph, threshold=2)

    hotspot_files = [path for path, _ in hotspots]
    # b.py and c.py both have fan-in=2
    assert "b.py" in hotspot_files
    assert "c.py" in hotspot_files


def test_high_fan_in_sorted_descending():
    """Results should be sorted by fan-in descending."""
    graph = _build_test_graph()
    hotspots = identify_high_fan_in(graph, threshold=1)

    fan_ins = [count for _, count in hotspots]
    assert fan_ins == sorted(fan_ins, reverse=True)


def test_high_fan_in_none_above_threshold():
    """If no file meets the threshold, return empty list."""
    graph = _build_test_graph()
    hotspots = identify_high_fan_in(graph, threshold=100)
    assert hotspots == []


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
