"""CK-ARCH-CONFIG-SPRAWL — Configuration Sprawl Detection.

Detects settings and configuration being accessed in inconsistent or
scattered ways across the codebase.  Flags direct os.environ access
outside settings modules, undeclared env vars, duplicated access, and
conflicting BaseSettings defaults.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from cathedral_keeper.models import Evidence, Finding, clamp_snippet, normalize_path
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_imports import read_text_best_effort


# ── public API ──────────────────────────────────────────────────────

def check_config_sprawl(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg
    settings_modules = list(inner_cfg.get("settings_modules") or ["**/settings.py", "**/config.py"])
    allow_direct_env = list(inner_cfg.get("allow_direct_env") or [
        "**/settings.py", "**/config.py", "**/conftest.py",
    ])

    severity = str(cfg.get("severity", "medium")).lower()

    # Phase 1: Collect all env var accesses and BaseSettings declarations
    env_accesses: List[_EnvAccess] = []       # (file, line, key, pattern)
    settings_fields: List[_SettingsField] = []  # (file, class, field, default)

    for f in files:
        try:
            rel = normalize_path(str(f.resolve().relative_to(root.resolve())))
        except ValueError:
            rel = normalize_path(str(f))

        source = read_text_best_effort(f)
        if not source.strip():
            continue

        is_settings_mod = matches_any(rel, settings_modules)
        is_allowed_direct = matches_any(rel, allow_direct_env)

        # Collect env accesses
        accesses = _find_env_accesses(source, rel)
        for acc in accesses:
            acc.is_settings_module = is_settings_mod
            acc.is_allowed = is_allowed_direct
        env_accesses.extend(accesses)

        # Collect BaseSettings fields
        if is_settings_mod:
            settings_fields.extend(_find_settings_fields(source, rel))

    # Phase 2: Analyse and produce findings
    findings: List[Finding] = []

    # 2a: Direct env access outside allowed modules
    findings.extend(_check_direct_access(env_accesses, severity="low"))

    # 2b: Env vars accessed but not declared in any BaseSettings
    declared_keys: Set[str] = {sf.field_name.upper() for sf in settings_fields}
    findings.extend(_check_undeclared_keys(env_accesses, declared_keys, severity="low"))

    # 2c: Same env var key accessed directly in >2 files
    findings.extend(_check_scattered_access(env_accesses, severity=severity))

    # 2d: Conflicting defaults in multiple BaseSettings classes
    findings.extend(_check_conflicting_defaults(settings_fields, severity=severity))

    return findings


# ── data containers ────────────────────────────────────────────────

class _EnvAccess:
    __slots__ = ("file", "line", "key", "pattern", "is_settings_module", "is_allowed")

    def __init__(self, file: str, line: int, key: str, pattern: str) -> None:
        self.file = file
        self.line = line
        self.key = key
        self.pattern = pattern
        self.is_settings_module = False
        self.is_allowed = False


class _SettingsField:
    __slots__ = ("file", "class_name", "field_name", "default_repr", "line")

    def __init__(self, file: str, class_name: str, field_name: str, default_repr: str, line: int) -> None:
        self.file = file
        self.class_name = class_name
        self.field_name = field_name
        self.default_repr = default_repr
        self.line = line


# ── detection: env accesses ────────────────────────────────────────

_ENV_PATTERNS = [
    # os.environ["KEY"], os.environ.get("KEY"), os.getenv("KEY")
    re.compile(r'''os\.environ\s*\[\s*['"]([^'"]+)['"]\s*\]'''),
    re.compile(r'''os\.environ\.get\s*\(\s*['"]([^'"]+)['"]'''),
    re.compile(r'''os\.getenv\s*\(\s*['"]([^'"]+)['"]'''),
]


def _find_env_accesses(source: str, rel_path: str) -> List[_EnvAccess]:
    accesses: List[_EnvAccess] = []
    for i, line_text in enumerate(source.splitlines(), start=1):
        for pat in _ENV_PATTERNS:
            for m in pat.finditer(line_text):
                accesses.append(_EnvAccess(
                    file=rel_path, line=i, key=m.group(1), pattern=pat.pattern,
                ))
    return accesses


# ── detection: BaseSettings fields ─────────────────────────────────

def _find_settings_fields(source: str, rel_path: str) -> List[_SettingsField]:
    """Find class fields in BaseSettings subclasses."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    fields: List[_SettingsField] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # Check if any base looks like BaseSettings or Settings
        is_settings = False
        for base in node.bases:
            base_name = _get_name(base)
            if base_name and ("BaseSettings" in base_name or "Settings" in base_name):
                is_settings = True
                break
        if not is_settings:
            continue

        # Collect annotated assignments (field declarations)
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                default_repr = ""
                if item.value is not None:
                    default_repr = ast.dump(item.value)
                fields.append(_SettingsField(
                    file=rel_path,
                    class_name=node.name,
                    field_name=field_name,
                    default_repr=default_repr,
                    line=item.lineno,
                ))

    return fields


def _get_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_get_name(node.value)}.{node.attr}"
    return ""


# ── analysis passes ────────────────────────────────────────────────

def _check_direct_access(accesses: List[_EnvAccess], *, severity: str) -> List[Finding]:
    """Flag os.environ access in non-settings modules."""
    findings: List[Finding] = []
    seen: Set[Tuple[str, int]] = set()  # dedupe by (file, line)

    for acc in accesses:
        if acc.is_allowed:
            continue
        key = (acc.file, acc.line)
        if key in seen:
            continue
        seen.add(key)

        findings.append(
            Finding(
                policy_id="CK-ARCH-CONFIG-SPRAWL",
                title=f"Direct env access: {acc.key} in {acc.file}",
                severity=severity,
                confidence="high",
                why_it_matters=(
                    f"'{acc.key}' is accessed via os.environ/os.getenv directly "
                    f"in application code instead of through a settings class. "
                    f"Scattered env access makes it impossible to know what "
                    f"configuration a service actually needs."
                ),
                evidence=[
                    Evidence(
                        file=acc.file,
                        line=acc.line,
                        snippet=clamp_snippet(f'os.environ/getenv("{acc.key}")'),
                        note="Direct environment variable access outside settings module",
                    )
                ],
                fix_options=[
                    "Move this access into a centralised settings/config module.",
                    f"Add the file pattern to allow_direct_env if this is intentional.",
                ],
                verification=[f"grep -n '{acc.key}' {acc.file}"],
                metadata={"key": acc.key, "file": acc.file},
            )
        )

    return findings


def _check_undeclared_keys(
    accesses: List[_EnvAccess], declared: Set[str], *, severity: str,
) -> List[Finding]:
    """Flag env var keys used in code but not declared in any BaseSettings."""
    if not declared:
        return []  # No BaseSettings found — skip (can't compare)

    findings: List[Finding] = []
    seen_keys: Set[str] = set()

    for acc in accesses:
        upper_key = acc.key.upper()
        if upper_key in declared or upper_key in seen_keys:
            continue
        seen_keys.add(upper_key)

        findings.append(
            Finding(
                policy_id="CK-ARCH-CONFIG-SPRAWL",
                title=f"Undeclared env var: {acc.key}",
                severity=severity,
                confidence="medium",
                why_it_matters=(
                    f"Environment variable '{acc.key}' is accessed in code but "
                    f"not declared in any BaseSettings class. Undeclared variables "
                    f"can silently differ between environments."
                ),
                evidence=[
                    Evidence(
                        file=acc.file,
                        line=acc.line,
                        snippet=clamp_snippet(f'os.environ/getenv("{acc.key}")'),
                        note="Not found in any BaseSettings declaration",
                    )
                ],
                fix_options=[
                    f"Add '{acc.key}' as a field in the appropriate BaseSettings class.",
                    "If this key is intentionally not settings-managed, document why.",
                ],
                verification=[f"grep -rn '{acc.key}' --include='*.py' ."],
                metadata={"key": acc.key, "first_seen_in": acc.file},
            )
        )

    return findings


def _check_scattered_access(accesses: List[_EnvAccess], *, severity: str) -> List[Finding]:
    """Flag env var keys accessed directly in >2 files."""
    key_to_files: Dict[str, Set[str]] = {}
    key_to_first: Dict[str, _EnvAccess] = {}

    for acc in accesses:
        k = acc.key
        if k not in key_to_files:
            key_to_files[k] = set()
            key_to_first[k] = acc
        key_to_files[k].add(acc.file)

    findings: List[Finding] = []
    for key, file_set in sorted(key_to_files.items()):
        if len(file_set) <= 2:
            continue
        first = key_to_first[key]
        sorted_files = sorted(file_set)
        findings.append(
            Finding(
                policy_id="CK-ARCH-CONFIG-SPRAWL",
                title=f"Scattered env access: {key} in {len(file_set)} files",
                severity=severity,
                confidence="high",
                why_it_matters=(
                    f"Environment variable '{key}' is accessed directly in "
                    f"{len(file_set)} different files, suggesting missing centralisation. "
                    f"Each access point is a place where environment differences can "
                    f"cause failures."
                ),
                evidence=[
                    Evidence(
                        file=f,
                        line=0,
                        snippet=clamp_snippet(f'accesses "{key}"'),
                        note=f"File {i + 1} of {len(sorted_files)}",
                    )
                    for i, f in enumerate(sorted_files[:5])
                ],
                fix_options=[
                    f"Centralise access to '{key}' in a single settings module.",
                    f"Inject the value via dependency injection instead of reading env directly.",
                ],
                verification=[f"grep -rn '{key}' --include='*.py' ."],
                metadata={"key": key, "files": sorted_files, "count": len(file_set)},
            )
        )

    return findings


def _check_conflicting_defaults(fields: List[_SettingsField], *, severity: str) -> List[Finding]:
    """Flag the same field name with different defaults across BaseSettings classes."""
    field_map: Dict[str, List[_SettingsField]] = {}
    for sf in fields:
        key = sf.field_name.lower()
        field_map.setdefault(key, []).append(sf)

    findings: List[Finding] = []
    for field_name, entries in sorted(field_map.items()):
        if len(entries) < 2:
            continue

        # Check if defaults differ
        defaults = {e.default_repr for e in entries if e.default_repr}
        if len(defaults) <= 1:
            continue  # All same or none have defaults

        findings.append(
            Finding(
                policy_id="CK-ARCH-CONFIG-SPRAWL",
                title=f"Conflicting defaults: {field_name} across {len(entries)} Settings classes",
                severity=severity,
                confidence="medium",
                why_it_matters=(
                    f"Field '{field_name}' is declared in {len(entries)} BaseSettings "
                    f"classes with different default values. This means the effective "
                    f"default depends on which class is instantiated, creating subtle "
                    f"environment-specific behaviour."
                ),
                evidence=[
                    Evidence(
                        file=e.file,
                        line=e.line,
                        snippet=clamp_snippet(f"{e.class_name}.{e.field_name} = {e.default_repr}"),
                        note=f"In class {e.class_name}",
                    )
                    for e in entries[:4]
                ],
                fix_options=[
                    "Consolidate into a single Settings class with one authoritative default.",
                    "If multiple classes are needed, ensure defaults are consistent.",
                ],
                verification=[f"grep -rn 'class.*Settings' --include='*.py' ."],
                metadata={
                    "field": field_name,
                    "classes": [f"{e.class_name} in {e.file}" for e in entries],
                },
            )
        )

    return findings
