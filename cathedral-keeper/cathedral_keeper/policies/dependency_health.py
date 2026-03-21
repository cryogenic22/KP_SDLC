"""CK-ARCH-DEPENDENCY-HEALTH — Dependency Age and Health.

Scans dependency declarations and flags architectural risks:
overlapping functionality, unused declared deps, undeclared used deps.
All analysis is offline (no network access required for core checks).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path
from cathedral_keeper.python_imports import read_text_best_effort


# ── built-in overlap categories ────────────────────────────────────

_DEFAULT_OVERLAP_CATEGORIES: Dict[str, List[str]] = {
    "http_client": ["requests", "httpx", "aiohttp", "urllib3"],
    "orm": ["sqlalchemy", "tortoise-orm", "peewee", "django"],
    "mongo": ["pymongo", "mongoengine", "motor"],
    "task_queue": ["celery", "dramatiq", "rq", "huey"],
    "web_framework": ["flask", "fastapi", "django", "starlette", "sanic"],
    "testing": ["pytest", "unittest2", "nose", "nose2"],
    "serialization": ["marshmallow", "pydantic", "attrs", "dataclasses-json"],
    "config": ["python-dotenv", "pydantic-settings", "dynaconf", "decouple"],
}


def check_dependency_health(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg

    dep_files = list(inner_cfg.get("dependency_files") or [
        "requirements.txt", "pyproject.toml", "requirements-dev.txt",
    ])
    overlap_cats = dict(inner_cfg.get("overlap_categories") or _DEFAULT_OVERLAP_CATEGORIES)

    severity = str(cfg.get("severity", "info")).lower()

    # Phase 1: Parse declared dependencies
    declared: Dict[str, _DeclaredDep] = {}
    for dep_rel in dep_files:
        dep_path = root / dep_rel
        if dep_path.exists():
            deps = _parse_dependency_file(dep_path, dep_rel)
            for d in deps:
                declared[d.name] = d

    if not declared:
        return []  # No dependency files found

    # Phase 2: Collect all top-level imports from source files
    imported_modules: Dict[str, Set[str]] = {}  # module -> set of files
    for f in files:
        try:
            rel = normalize_path(str(f.resolve().relative_to(root.resolve())))
        except ValueError:
            rel = normalize_path(str(f))
        source = read_text_best_effort(f)
        if not source.strip():
            continue
        for mod in _extract_top_level_imports(source):
            imported_modules.setdefault(mod, set()).add(rel)

    findings: List[Finding] = []

    # Check 1: Overlapping functionality
    findings.extend(_check_overlap(declared, overlap_cats, severity="info"))

    # Check 2: Declared but never imported (unused deps)
    findings.extend(_check_unused_deps(declared, imported_modules, severity="low"))

    # Check 3: Imported but not declared (transitive dependency usage)
    findings.extend(_check_undeclared_imports(declared, imported_modules, severity="low"))

    return findings


# ── data containers ────────────────────────────────────────────────

class _DeclaredDep:
    __slots__ = ("name", "version_spec", "source_file", "line")

    def __init__(self, name: str, version_spec: str, source_file: str, line: int) -> None:
        self.name = name
        self.version_spec = version_spec
        self.source_file = source_file
        self.line = line


# ── dependency file parsing ────────────────────────────────────────

def _parse_dependency_file(path: Path, rel_path: str) -> List[_DeclaredDep]:
    name = path.name.lower()
    if name == "pyproject.toml":
        return _parse_pyproject(path, rel_path)
    # requirements*.txt
    return _parse_requirements_txt(path, rel_path)


def _parse_requirements_txt(path: Path, rel_path: str) -> List[_DeclaredDep]:
    deps: List[_DeclaredDep] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps

    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Handle: package>=1.0, package==1.0, package~=1.0, bare package
        m = re.match(r'^([A-Za-z0-9_][A-Za-z0-9._-]*)\s*([<>=!~].*)?', line)
        if m:
            pkg_name = _normalize_pkg_name(m.group(1))
            version = (m.group(2) or "").strip()
            deps.append(_DeclaredDep(name=pkg_name, version_spec=version, source_file=rel_path, line=i))
    return deps


def _parse_pyproject(path: Path, rel_path: str) -> List[_DeclaredDep]:
    """Minimal pyproject.toml parser for [project.dependencies] and [tool.poetry.dependencies]."""
    deps: List[_DeclaredDep] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return deps

    # Look for dependencies = [...] sections
    in_deps = False
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        if stripped in ("dependencies = [", 'dependencies = ['):
            in_deps = True
            continue
        if in_deps:
            if stripped == "]":
                in_deps = False
                continue
            # Parse "package>=1.0", or "package",
            m = re.match(r'''^\s*['"]([A-Za-z0-9_][A-Za-z0-9._-]*)([<>=!~\[\]].*)?\s*['"]''', stripped)
            if m:
                pkg = _normalize_pkg_name(m.group(1))
                ver = (m.group(2) or "").rstrip('",').strip()
                deps.append(_DeclaredDep(name=pkg, version_spec=ver, source_file=rel_path, line=i))

    return deps


def _normalize_pkg_name(name: str) -> str:
    """Normalize package name: lowercase, replace - and _ consistently."""
    return re.sub(r'[-_.]+', '-', name.strip().lower())


# ── import extraction ──────────────────────────────────────────────

# Map of common import names that differ from package names
_IMPORT_TO_PACKAGE: Dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "gi": "pygobject",
    "serial": "pyserial",
    "usb": "pyusb",
    "attr": "attrs",
    "jwt": "pyjwt",
    "magic": "python-magic",
    "lxml": "lxml",
}

# Stdlib modules to ignore (Python 3.10+ builtins — not exhaustive but covers common ones)
_STDLIB_MODULES: Set[str] = {
    "abc", "ast", "asyncio", "base64", "builtins", "collections", "concurrent",
    "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
    "difflib", "email", "enum", "errno", "fnmatch", "fractions", "functools",
    "gc", "gettext", "glob", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "importlib", "inspect", "io", "itertools", "json", "keyword", "locale",
    "logging", "math", "mmap", "multiprocessing", "numbers", "operator", "os",
    "pathlib", "pickle", "platform", "pprint", "queue", "random", "re",
    "secrets", "select", "shelve", "shlex", "shutil", "signal", "site", "socket",
    "sqlite3", "ssl", "stat", "statistics", "string", "struct", "subprocess",
    "sys", "tempfile", "textwrap", "threading", "time", "timeit", "token",
    "tokenize", "traceback", "turtle", "types", "typing", "unicodedata",
    "unittest", "urllib", "uuid", "venv", "warnings", "weakref", "webbrowser",
    "xml", "xmlrpc", "zipfile", "zipimport", "zlib",
    # common sub-modules people import as top-level
    "posixpath", "ntpath", "encodings", "_thread",
}


def _extract_top_level_imports(source: str) -> Set[str]:
    """Extract top-level imported package names (first component of import)."""
    modules: Set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        # import foo, import foo.bar
        m = re.match(r'^import\s+([A-Za-z_][A-Za-z0-9_]*)', stripped)
        if m:
            modules.add(m.group(1))
        # from foo import ..., from foo.bar import ...
        m = re.match(r'^from\s+([A-Za-z_][A-Za-z0-9_]*)', stripped)
        if m:
            modules.add(m.group(1))
    return modules


# ── analysis passes ────────────────────────────────────────────────

def _check_overlap(
    declared: Dict[str, _DeclaredDep],
    categories: Dict[str, List[str]],
    *,
    severity: str,
) -> List[Finding]:
    """Flag overlapping packages in the same category."""
    findings: List[Finding] = []
    declared_names = set(declared.keys())

    for cat_name, cat_packages in sorted(categories.items()):
        normed_cat = [_normalize_pkg_name(p) for p in cat_packages]
        present = [p for p in normed_cat if p in declared_names]
        if len(present) < 2:
            continue

        evidence = []
        for pkg in present:
            dep = declared[pkg]
            evidence.append(Evidence(
                file=dep.source_file,
                line=dep.line,
                snippet=f"{pkg} {dep.version_spec}".strip(),
                note=f"Category: {cat_name}",
            ))

        findings.append(
            Finding(
                policy_id="CK-ARCH-DEPENDENCY-HEALTH",
                title=f"Overlapping deps ({cat_name}): {', '.join(present)}",
                severity=severity,
                confidence="medium",
                why_it_matters=(
                    f"Multiple packages serving the same purpose ({cat_name}) "
                    f"are declared: {', '.join(present)}. This indicates architectural "
                    f"indecision and increases the maintenance and security surface."
                ),
                evidence=evidence,
                fix_options=[
                    f"Standardise on one {cat_name} package and remove the others.",
                    "If both are genuinely needed, document the reason.",
                ],
                verification=[f"grep -rn '{present[0]}\\|{present[1]}' --include='*.py' ."],
                metadata={"category": cat_name, "packages": present},
            )
        )

    return findings


def _check_unused_deps(
    declared: Dict[str, _DeclaredDep],
    imported: Dict[str, Set[str]],
    *,
    severity: str,
) -> List[Finding]:
    """Flag declared dependencies that are never imported."""
    # Build reverse map: package name -> possible import names
    pkg_to_imports: Dict[str, Set[str]] = {}
    for pkg_name in declared:
        # The import name is usually the package name with - replaced by _
        import_name = pkg_name.replace("-", "_")
        pkg_to_imports.setdefault(pkg_name, set()).add(import_name)

    # Add known reverse mappings
    for imp, pkg in _IMPORT_TO_PACKAGE.items():
        normed_pkg = _normalize_pkg_name(pkg)
        if normed_pkg in declared:
            pkg_to_imports.setdefault(normed_pkg, set()).add(imp)

    # Packages that shouldn't be flagged (build/test tools, plugins)
    skip_patterns = {
        "setuptools", "wheel", "pip", "build", "twine",
        "black", "isort", "flake8", "mypy", "pylint", "ruff",
        "pytest", "coverage", "tox", "nox",
        "pre-commit", "commitizen",
    }

    all_imported_lower = {m.lower() for m in imported}
    findings: List[Finding] = []

    for pkg_name, dep in sorted(declared.items()):
        if pkg_name in skip_patterns:
            continue

        possible_imports = pkg_to_imports.get(pkg_name, {pkg_name.replace("-", "_")})
        is_used = any(pi.lower() in all_imported_lower for pi in possible_imports)
        if is_used:
            continue

        findings.append(
            Finding(
                policy_id="CK-ARCH-DEPENDENCY-HEALTH",
                title=f"Unused dependency: {pkg_name}",
                severity=severity,
                confidence="low",
                why_it_matters=(
                    f"Package '{pkg_name}' is declared in {dep.source_file} but "
                    f"never imported in any source file. Unused dependencies "
                    f"increase install time and attack surface."
                ),
                evidence=[
                    Evidence(
                        file=dep.source_file,
                        line=dep.line,
                        snippet=f"{pkg_name} {dep.version_spec}".strip(),
                        note="Declared but no matching imports found",
                    )
                ],
                fix_options=[
                    f"Remove '{pkg_name}' from {dep.source_file} if genuinely unused.",
                    "If it's a plugin or runtime dependency, add it to skip list.",
                ],
                verification=[f"grep -rn '{pkg_name.replace('-', '_')}' --include='*.py' ."],
                metadata={"package": pkg_name, "source_file": dep.source_file},
            )
        )

    return findings


def _check_undeclared_imports(
    declared: Dict[str, _DeclaredDep],
    imported: Dict[str, Set[str]],
    *,
    severity: str,
) -> List[Finding]:
    """Flag imported modules that aren't declared as dependencies."""
    # Build set of all possible import names from declared packages
    known_imports: Set[str] = set()
    for pkg_name in declared:
        known_imports.add(pkg_name.replace("-", "_").lower())
        # Also add the raw name
        known_imports.add(pkg_name.lower())

    for imp, pkg in _IMPORT_TO_PACKAGE.items():
        if _normalize_pkg_name(pkg) in declared:
            known_imports.add(imp.lower())

    findings: List[Finding] = []
    for mod, mod_files in sorted(imported.items()):
        mod_lower = mod.lower()

        # Skip stdlib
        if mod_lower in _STDLIB_MODULES:
            continue

        # Skip internal imports (likely project modules)
        if mod_lower.startswith("_") or mod_lower in known_imports:
            continue

        # Skip if any declared package could provide this import
        is_known = False
        for pkg_name in declared:
            if mod_lower == pkg_name.replace("-", "_").lower():
                is_known = True
                break
        if is_known:
            continue

        # Heuristic: if the module is imported in only 1 file and looks
        # like a local/project import, skip it
        if len(mod_files) <= 1:
            continue  # Likely a project-internal module

        sorted_files = sorted(mod_files)
        findings.append(
            Finding(
                policy_id="CK-ARCH-DEPENDENCY-HEALTH",
                title=f"Undeclared dependency: {mod}",
                severity=severity,
                confidence="low",
                why_it_matters=(
                    f"Module '{mod}' is imported in {len(mod_files)} files but "
                    f"not declared in any dependency file. This likely relies on "
                    f"a transitive dependency, which can break unexpectedly."
                ),
                evidence=[
                    Evidence(
                        file=f,
                        line=0,
                        snippet=f"import {mod}",
                        note=f"File {i + 1} of {len(sorted_files)}",
                    )
                    for i, f in enumerate(sorted_files[:3])
                ],
                fix_options=[
                    f"Add '{mod}' to requirements.txt or pyproject.toml.",
                    f"If '{mod}' is a project module, this can be ignored.",
                ],
                verification=[f"pip show {mod}"],
                metadata={"module": mod, "files": sorted_files},
            )
        )

    return findings
