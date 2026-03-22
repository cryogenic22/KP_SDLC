"""Test Recommendation Engine for Cathedral Keeper.

Analyzes an import graph to recommend which test files to run
based on which source files have changed.
"""

from __future__ import annotations

import os
from collections import deque


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a test file."""
    basename = os.path.basename(path)
    if basename.startswith("test_") and basename.endswith(".py"):
        return True
    if basename.endswith("_test.py"):
        return True
    # Also match anything living under a /tests/ directory
    if "/tests/" in path:
        return True
    return False


def recommend_tests(
    *,
    changed_files: list[str],
    import_graph: dict[str, list[str]],
) -> list[str]:
    """Recommend test files affected by *changed_files*.

    Parameters
    ----------
    changed_files:
        List of file paths that were modified.
    import_graph:
        Mapping of ``file -> [files it imports]``.  For example,
        ``{"src/api.py": ["src/models.py"]}`` means *api.py* imports
        *models.py*.

    Returns
    -------
    list[str]
        Sorted, deduplicated list of test file paths that are
        transitively affected by the change.  Direct importers appear
        before transitive importers.
    """
    if not changed_files:
        return []

    # 1. Build the REVERSE graph: for each file, who imports it?
    reverse: dict[str, list[str]] = {}
    for importer, imports in import_graph.items():
        for dep in imports:
            reverse.setdefault(dep, []).append(importer)

    # 2. BFS from every changed file through the reverse graph.
    #    Track the depth at which each file is first reached.
    depth: dict[str, int] = {}

    queue: deque[tuple[str, int]] = deque()
    visited: set[str] = set()

    for f in changed_files:
        if f not in visited:
            visited.add(f)
            depth[f] = 0
            queue.append((f, 0))

    while queue:
        node, d = queue.popleft()
        for neighbour in reverse.get(node, []):
            if neighbour not in visited:
                visited.add(neighbour)
                depth[neighbour] = d + 1
                queue.append((neighbour, d + 1))

    # 3. Filter to test files only.
    test_files = [f for f in visited if _is_test_file(f)]

    # 4. Sort by BFS depth (direct importers first), then alphabetically
    #    as a stable tie-breaker.
    test_files.sort(key=lambda f: (depth[f], f))

    # 5. Deduplicate (list is already unique from BFS, but be safe).
    seen: set[str] = set()
    result: list[str] = []
    for f in test_files:
        if f not in seen:
            seen.add(f)
            result.append(f)

    return result
