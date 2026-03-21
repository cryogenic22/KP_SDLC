"""CK-ARCH-TEST-ALIGNMENT — Test Architecture Alignment.

Verifies that the test directory structure mirrors the source structure
and that architectural boundary interfaces have test coverage.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_graph import build_import_graph, build_module_index


def check_test_alignment(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg

    source_roots = list(inner_cfg.get("source_roots") or [])
    test_roots = list(inner_cfg.get("test_roots") or ["tests"])
    test_pattern = str(inner_cfg.get("test_pattern", "test_{module}.py"))
    require_boundary_tests = bool(inner_cfg.get("require_boundary_tests", True))
    require_llm_evals = bool(inner_cfg.get("require_llm_evals", False))

    root_resolved = root.resolve()

    # Build resolved sets
    all_test_files = _collect_test_files(root_resolved, test_roots)
    test_stems: Set[str] = set()
    for tf in all_test_files:
        test_stems.add(tf.stem)          # e.g. "test_parser"
        test_stems.add(tf.stem.replace("test_", ""))  # e.g. "parser"

    severity_missing = str(cfg.get("severity", "low")).lower()
    findings: List[Finding] = []

    # Determine source files to check
    source_files = _filter_source_files(root_resolved, files, source_roots)

    # Check 1: Source modules without corresponding test files
    for src_path in source_files:
        try:
            rel = normalize_path(str(src_path.resolve().relative_to(root_resolved)))
        except ValueError:
            rel = normalize_path(str(src_path))

        module_stem = src_path.stem  # e.g. "parser"
        if module_stem.startswith("__"):
            continue  # skip __init__, __main__, etc.

        # Check if a test file exists
        expected_test_stem = test_pattern.replace("{module}", module_stem).replace(".py", "")
        if expected_test_stem in test_stems or f"test_{module_stem}" in test_stems:
            continue

        findings.append(
            Finding(
                policy_id="CK-ARCH-TEST-ALIGNMENT",
                title=f"Missing test file for: {rel}",
                severity=severity_missing,
                confidence="medium",
                why_it_matters=(
                    f"Source module '{rel}' has no corresponding test file. "
                    f"Gaps in test architecture tend to cluster at the exact "
                    f"points where bugs are most expensive."
                ),
                evidence=[
                    Evidence(
                        file=rel,
                        line=1,
                        snippet=f"Expected: {test_pattern.replace('{module}', module_stem)}",
                        note="No matching test file found in test roots",
                    )
                ],
                fix_options=[
                    f"Create a test file: {test_pattern.replace('{module}', module_stem)}",
                    "If this module is tested indirectly, add it to exclusions.",
                ],
                verification=[f"find . -name '{test_pattern.replace('{module}', module_stem)}'"],
                metadata={"source_file": rel, "module": module_stem},
            )
        )

    # Check 2: Boundary interface modules should have tests (higher severity)
    if require_boundary_tests:
        findings.extend(
            _check_boundary_tests(
                root=root_resolved,
                files=files,
                python_roots=python_roots,
                test_stems=test_stems,
                test_pattern=test_pattern,
            )
        )

    # Check 3: LangChain modules should have eval cases
    if require_llm_evals:
        findings.extend(
            _check_llm_evals(
                root=root_resolved,
                files=files,
                test_stems=test_stems,
            )
        )

    return findings


# ── internal helpers ───────────────────────────────────────────────

def _collect_test_files(root: Path, test_roots: List[str]) -> List[Path]:
    """Collect all test_*.py files from the test roots."""
    test_files: List[Path] = []
    for tr in test_roots:
        test_dir = root / tr
        if test_dir.exists():
            for p in test_dir.rglob("test_*.py"):
                test_files.append(p)
            for p in test_dir.rglob("*_test.py"):
                test_files.append(p)
    return test_files


def _filter_source_files(root: Path, files: List[Path], source_roots: List[str]) -> List[Path]:
    """Filter files to only those under source roots (or all if no source roots configured)."""
    if not source_roots:
        # No source roots: use all non-test files
        return [f for f in files if not _is_test_file(f)]

    out: List[Path] = []
    for f in files:
        try:
            rel = f.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        for sr in source_roots:
            if rel.startswith(sr.rstrip("/") + "/") or rel == sr:
                if not _is_test_file(f):
                    out.append(f)
                break
    return out


def _is_test_file(path: Path) -> bool:
    name = path.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "conftest" in name
        or "/tests/" in path.as_posix()
        or "/test/" in path.as_posix()
    )


def _check_boundary_tests(
    *,
    root: Path,
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
    test_stems: Set[str],
    test_pattern: str,
) -> List[Finding]:
    """Check that modules imported across layers have test coverage."""
    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    # Count incoming cross-directory imports per file
    cross_imports: Dict[str, int] = {}
    for edge in graph.edges:
        src_dir = str(Path(edge.src_file).parent)
        dst_dir = str(Path(edge.dst_file).parent)
        if src_dir != dst_dir:
            cross_imports[edge.dst_file] = cross_imports.get(edge.dst_file, 0) + 1

    # Files with >= 2 cross-directory importers are boundary interfaces
    findings: List[Finding] = []
    for file_path, count in sorted(cross_imports.items(), key=lambda x: -x[1]):
        if count < 2:
            continue
        stem = Path(file_path).stem
        if stem.startswith("__"):
            continue

        expected = test_pattern.replace("{module}", stem).replace(".py", "")
        if expected in test_stems or f"test_{stem}" in test_stems:
            continue

        findings.append(
            Finding(
                policy_id="CK-ARCH-TEST-ALIGNMENT",
                title=f"Untested boundary interface: {file_path}",
                severity="medium",
                confidence="medium",
                why_it_matters=(
                    f"'{file_path}' is imported by {count} modules across different "
                    f"directories, making it a boundary interface. Boundary modules "
                    f"are higher-risk and should have dedicated test coverage."
                ),
                evidence=[
                    Evidence(
                        file=file_path,
                        line=1,
                        snippet=f"Imported across {count} directory boundaries",
                        note="Boundary interface without test coverage",
                    )
                ],
                fix_options=[
                    f"Create {test_pattern.replace('{module}', stem)} with tests for this interface.",
                ],
                verification=[f"grep -rn 'import.*{stem}' --include='*.py' ."],
                metadata={"file": file_path, "cross_imports": count},
            )
        )

    return findings


def _check_llm_evals(
    *,
    root: Path,
    files: List[Path],
    test_stems: Set[str],
) -> List[Finding]:
    """Flag modules with LangChain/LangGraph imports that lack eval test files."""
    import re
    _LANGCHAIN_PAT = re.compile(r"(?:from|import)\s+(?:langchain|langgraph)")

    findings: List[Finding] = []
    for f in files:
        if _is_test_file(f):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not _LANGCHAIN_PAT.search(text):
            continue

        try:
            rel = normalize_path(str(f.resolve().relative_to(root)))
        except ValueError:
            rel = normalize_path(str(f))

        stem = f.stem
        if f"test_{stem}" in test_stems or f"eval_{stem}" in test_stems:
            continue

        findings.append(
            Finding(
                policy_id="CK-ARCH-TEST-ALIGNMENT",
                title=f"LLM module without eval: {rel}",
                severity="info",
                confidence="low",
                why_it_matters=(
                    f"'{rel}' uses LangChain/LangGraph but has no corresponding "
                    f"eval test file. LLM-integrated code benefits from evaluation "
                    f"suites to catch regression in prompt/chain behaviour."
                ),
                evidence=[
                    Evidence(
                        file=rel,
                        line=1,
                        snippet="Uses langchain/langgraph imports",
                        note="No eval_*.py or test_*.py file found",
                    )
                ],
                fix_options=[
                    f"Create an eval test file: eval_{stem}.py or test_{stem}.py",
                ],
                verification=[f"grep -rn 'langchain\\|langgraph' {rel}"],
                metadata={"file": rel},
            )
        )

    return findings
