"""CK-ARCH-DEAD-MODULES — Dead Module Detection.

Identifies Python files that exist in the project but are never imported
by anything and don't serve as entry points.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_graph import build_import_graph, build_module_index


# Default entry-point patterns (files that are legitimately never imported)
_DEFAULT_ENTRY_PATTERNS = [
    "**/cli.py",
    "**/__main__.py",
    "**/conftest.py",
    "**/test_*.py",
    "**/*_test.py",
    "**/tests/**",
    "**/test/**",
    "**/celery_*.py",
    "**/migrations/**",
    "**/alembic/**",
    "**/manage.py",
    "**/setup.py",
    "**/setup.cfg",
    "**/pyproject.toml",
    "**/tasks.py",
    "ck.py",
    "**/quality_gate.py",
    "**/__init__.py",
]


def check_dead_modules(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg
    entry_patterns = list(inner_cfg.get("entry_point_patterns") or _DEFAULT_ENTRY_PATTERNS)

    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    # Build set of all files in the graph that have incoming edges
    imported_files: Set[str] = set()
    for edge in graph.edges:
        imported_files.add(normalize_path(edge.dst_file))

    # All analysed files
    all_files: Set[str] = set()
    for f in files:
        try:
            rel = f.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = f.as_posix()
        all_files.add(normalize_path(rel))

    severity = str(cfg.get("severity", "low")).lower()
    findings: List[Finding] = []
    total_files = len(all_files)

    dead_files: List[str] = []
    for rel in sorted(all_files):
        # Skip if something imports this file
        if rel in imported_files:
            continue

        # Skip entry points / test files
        if matches_any(rel, entry_patterns):
            continue

        dead_files.append(rel)

    for rel in dead_files:
        findings.append(
            Finding(
                policy_id="CK-ARCH-DEAD-MODULES",
                title=f"Dead module: {rel}",
                severity=severity,
                confidence="medium",
                why_it_matters=(
                    "This file is never imported by any other module and doesn't "
                    "match known entry-point patterns.  Dead modules confuse "
                    "developers, mislead AI tools, and increase maintenance burden."
                ),
                evidence=[
                    Evidence(
                        file=rel,
                        line=1,
                        snippet="(no incoming imports)",
                        note=f"Not imported by any analysed file ({len(dead_files)} dead out of {total_files} total files)",
                    )
                ],
                fix_options=[
                    "Delete the file if it is genuinely unused.",
                    "If it is a legitimate entry point, add its pattern to entry_point_patterns in config.",
                ],
                verification=[f"grep -r 'import.*{Path(rel).stem}' --include='*.py' ."],
                metadata={
                    "file": rel,
                    "total_files_analysed": total_files,
                    "total_dead_files": len(dead_files),
                    "unit": "files",
                },
            )
        )

    return findings
