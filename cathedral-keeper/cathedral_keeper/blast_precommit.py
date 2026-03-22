"""Commit-Aware Blast Radius — pre-commit integration.

Computes which downstream files are transitively affected by a set of
changed files, using a project-level import graph.  Designed to run as a
pre-commit hook so developers see the ripple effect *before* they push.
"""

from __future__ import annotations

from collections import deque


def compute_commit_blast_radius(
    *,
    changed_files: list[str],
    import_graph: dict[str, list[str]],
) -> dict:
    """Return the transitive blast radius for *changed_files*.

    Parameters
    ----------
    changed_files:
        Files that were modified in this commit.
    import_graph:
        Maps ``file -> [files it imports]``.  We invert this to find
        *reverse* dependencies (who imports each file).

    Returns
    -------
    dict with keys ``changed_files``, ``affected_files``,
    ``total_affected``, ``source_files_affected``, ``test_files_affected``.
    """
    # Build reverse graph: file -> set of files that import it.
    reverse: dict[str, set[str]] = {}
    for importer, imports in import_graph.items():
        for dep in imports:
            reverse.setdefault(dep, set()).add(importer)

    # BFS from every changed file through the reverse graph.
    changed_set = set(changed_files)
    affected: set[str] = set()
    queue: deque[str] = deque(changed_files)
    visited: set[str] = set(changed_files)

    while queue:
        current = queue.popleft()
        for dependent in reverse.get(current, set()):
            if dependent not in visited:
                visited.add(dependent)
                affected.add(dependent)
                queue.append(dependent)

    # Exclude the changed files themselves from affected.
    affected -= changed_set

    affected_list = sorted(affected)

    test_files = [f for f in affected_list if _is_test_file(f)]
    source_files = [f for f in affected_list if not _is_test_file(f)]

    return {
        "changed_files": changed_files,
        "affected_files": affected_list,
        "total_affected": len(affected_list),
        "source_files_affected": len(source_files),
        "test_files_affected": len(test_files),
    }


def format_blast_summary(result: dict) -> str:
    """Format a blast-radius *result* dict as a human-readable string."""
    affected = result["affected_files"]
    changed = result["changed_files"]
    total = result["total_affected"]

    if total == 0:
        return "\u2713 No downstream files affected by this change."

    changed_names = ", ".join(_basename(f) for f in changed)

    source_files = [f for f in affected if not _is_test_file(f)]
    test_files = [f for f in affected if _is_test_file(f)]

    lines = [
        f"\u26a1 Blast Radius: This change to {changed_names} affects {total} file{'s' if total != 1 else ''}",
    ]
    if source_files:
        lines.append(f"  Source files: {', '.join(source_files)}")
    if test_files:
        lines.append(f"  Test files: {', '.join(test_files)}")

    return "\n".join(lines)


# ── helpers ──────────────────────────────────────────────────────────


def _is_test_file(path: str) -> bool:
    """Heuristic: a file is a test if its basename starts with ``test_``
    or it lives under a ``tests/`` directory."""
    parts = path.replace("\\", "/").split("/")
    basename = parts[-1]
    return basename.startswith("test_") or "tests" in parts


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]
