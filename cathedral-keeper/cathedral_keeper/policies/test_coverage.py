"""Phase 4 — CK-ARCH-TEST-COVERAGE: TESTED_BY Edge Detection.

Analyzes test file imports to create TESTED_BY edges and flags
source files with zero test coverage.

Upgrades CK's existing test-alignment policy (which only checks naming
conventions) with actual import-based coverage detection.

Technique from code-review-graph which tracks TESTED_BY edges in its graph.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any, Dict, List

from cathedral_keeper.models import Evidence, Finding
from cathedral_keeper.python_graph import PyGraph


# ── Test file detection ──────────────────────────────────────────────

_TEST_PATTERNS = [
    re.compile(r"(^|/)tests?/test_[^/]+\.py$"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"(^|/)[^/]+_test\.py$"),
]

_EXCLUDED_FILES = {
    "__init__.py",
    "conftest.py",
    "setup.py",
    "manage.py",
}


def _is_test_file(path: str) -> bool:
    """Check if path is a test file."""
    return any(p.search(path) for p in _TEST_PATTERNS)


def _is_excluded_source(path: str) -> bool:
    """Check if a source file should be excluded from coverage analysis."""
    basename = path.rsplit("/", 1)[-1] if "/" in path else path
    return basename in _EXCLUDED_FILES


# ── Core functions ───────────────────────────────────────────────────


def detect_test_edges(
    graph: PyGraph,
    *,
    test_pattern: str = "test_*.py",
) -> Dict[str, List[str]]:
    """Analyze test file imports to create TESTED_BY mapping.

    For each test file in the graph, examines what source files it imports.
    Creates a mapping: source_file → [test_files_that_import_it].

    Args:
        graph: Import graph with forward edges.
        test_pattern: Glob pattern for test files (for future use).

    Returns:
        Dict mapping source_file → list of test files that import it.
    """
    tested_by: Dict[str, List[str]] = {}

    for edge in graph.edges:
        # Only consider edges where source is a test file
        if not _is_test_file(edge.src_file):
            continue

        # Target must be a non-test, non-excluded source file
        if _is_test_file(edge.dst_file):
            continue
        if _is_excluded_source(edge.dst_file):
            continue

        tested_by.setdefault(edge.dst_file, []).append(edge.src_file)

    return tested_by


def check_test_coverage(
    *,
    graph: PyGraph,
    source_files: List[str],
    cfg: Dict[str, Any],
) -> List[Finding]:
    """Flag source files with zero TESTED_BY edges.

    Args:
        graph: Import graph.
        source_files: List of source file relative paths to check.
        cfg: Policy config with optional keys:
            - severity (str): Finding severity (default: "low")
            - exclude_patterns (list[str]): Glob patterns to exclude

    Returns:
        List of findings for untested source files.
    """
    severity = str(cfg.get("severity", "low"))
    exclude_patterns = list(cfg.get("exclude_patterns", []) or [])

    tested_by = detect_test_edges(graph)
    findings: List[Finding] = []

    for source_file in source_files:
        # Skip excluded files
        if _is_excluded_source(source_file):
            continue

        # Skip files matching exclude patterns
        if any(fnmatch(source_file, pat) for pat in exclude_patterns):
            continue

        # Check if any test imports this file
        test_files = tested_by.get(source_file, [])
        if not test_files:
            findings.append(
                Finding(
                    policy_id="CK-ARCH-TEST-COVERAGE",
                    title=f"No test imports {source_file}",
                    severity=severity,
                    confidence="medium",
                    why_it_matters=(
                        f"{source_file} has no test files that import it directly. "
                        f"This means changes to this module may not be caught by any test. "
                        f"Consider adding a test file that imports and exercises its public API."
                    ),
                    evidence=[
                        Evidence(
                            file=source_file,
                            line=0,
                            snippet="No TESTED_BY edges detected",
                            note="No test file imports this module",
                        )
                    ],
                    fix_options=[
                        f"Create a test file that imports and tests {source_file}.",
                        f"If tested indirectly (integration tests), add a direct import to make the coverage explicit.",
                    ],
                    verification=[f"grep -r 'import.*{source_file.replace('/', '.').replace('.py', '')}' tests/"],
                    metadata={
                        "source_file": source_file,
                        "tested_by": [],
                    },
                )
            )

    return findings
