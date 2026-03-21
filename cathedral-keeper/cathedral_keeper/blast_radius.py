"""Phase 2 — Blast-Radius Analysis.

Given changed files and an import graph, computes the blast radius:
all files that directly or transitively depend on the changed files,
plus affected test files.

Technique inspired by code-review-graph (tirth8205/code-review-graph),
a Claude Code MCP plugin that builds persistent structural graphs using
Tree-sitter and provides blast-radius analysis.

CK already builds an import graph in python_graph.py. This module adds
reverse-edge traversal on top of it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from cathedral_keeper.python_graph import PyGraph


# ── Test file detection ──────────────────────────────────────────────

_TEST_PATTERNS = [
    re.compile(r"(^|/)tests?/"),           # files in tests/ or test/ dirs
    re.compile(r"(^|/)test_[^/]+\.py$"),   # test_*.py anywhere
    re.compile(r"(^|/)[^/]+_test\.py$"),   # *_test.py anywhere
    re.compile(r"\.spec\.[jt]sx?$"),       # *.spec.ts/js
    re.compile(r"\.test\.[jt]sx?$"),       # *.test.ts/js
]


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file."""
    return any(p.search(path) for p in _TEST_PATTERNS)


# ── Data structures ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BlastRadius:
    """Result of blast-radius analysis."""

    changed_files: List[str]
    direct_dependents: List[str]
    transitive_dependents: List[str]
    affected_tests: List[str]
    fan_in_scores: Dict[str, int]


# ── Core functions ───────────────────────────────────────────────────


def build_reverse_index(graph: PyGraph) -> Dict[str, List[str]]:
    """Build reverse-edge index: for each file, who imports it.

    Given edge A→B (A imports B), the reverse index maps B → [A, ...].
    This answers: "if B changes, who is affected?"
    """
    rev: Dict[str, List[str]] = {}
    for edge in graph.edges:
        rev.setdefault(edge.dst_file, []).append(edge.src_file)
    return rev


def compute_blast_radius(
    graph: PyGraph,
    changed_files: list[str],
    *,
    include_tests: bool = True,
    max_depth: int = 3,
) -> BlastRadius:
    """BFS on reverse import edges from changed files.

    Args:
        graph: Import graph with forward edges (A imports B = A→B).
        changed_files: Files that were modified.
        include_tests: Whether to identify affected test files.
        max_depth: Maximum BFS depth (limits transitive traversal).

    Returns:
        BlastRadius with direct dependents, transitive dependents,
        affected tests, and fan-in scores.
    """
    if not changed_files:
        return BlastRadius(
            changed_files=[],
            direct_dependents=[],
            transitive_dependents=[],
            affected_tests=[],
            fan_in_scores={},
        )

    rev = build_reverse_index(graph)
    changed_set = set(changed_files)

    # BFS with depth tracking
    visited: Set[str] = set(changed_files)
    direct: Set[str] = set()
    transitive: Set[str] = set()

    queue: deque[Tuple[str, int]] = deque()
    for f in changed_files:
        for dep in rev.get(f, []):
            if dep not in visited:
                queue.append((dep, 1))
                visited.add(dep)

    while queue:
        node, depth = queue.popleft()

        if depth == 1:
            direct.add(node)
        else:
            transitive.add(node)

        if depth < max_depth:
            for dep in rev.get(node, []):
                if dep not in visited:
                    visited.add(dep)
                    queue.append((dep, depth + 1))

    # Identify affected tests from all dependents
    all_dependents = direct | transitive
    affected_tests: List[str] = []
    if include_tests:
        affected_tests = sorted(f for f in all_dependents if _is_test_file(f))

    # Compute fan-in scores for all files in the graph
    fan_in: Dict[str, int] = {}
    for edge in graph.edges:
        fan_in[edge.dst_file] = fan_in.get(edge.dst_file, 0) + 1

    return BlastRadius(
        changed_files=list(changed_files),
        direct_dependents=sorted(direct),
        transitive_dependents=sorted(transitive),
        affected_tests=affected_tests,
        fan_in_scores=fan_in,
    )


def identify_high_fan_in(
    graph: PyGraph,
    *,
    threshold: int = 10,
) -> List[Tuple[str, int]]:
    """Identify files with high fan-in (many dependents).

    High fan-in files are "god modules" — changes to them have
    outsized blast radius. They deserve extra review and testing.

    Returns:
        List of (file_path, fan_in_count) sorted by fan_in descending.
    """
    fan_in: Dict[str, int] = {}
    for edge in graph.edges:
        fan_in[edge.dst_file] = fan_in.get(edge.dst_file, 0) + 1

    hotspots = [(path, count) for path, count in fan_in.items() if count >= threshold]
    return sorted(hotspots, key=lambda x: x[1], reverse=True)
