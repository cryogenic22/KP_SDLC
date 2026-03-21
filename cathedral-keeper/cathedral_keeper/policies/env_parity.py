"""CK-ARCH-ENV-PARITY — Environment Parity Checks.

Detects code paths that behave differently across environments and
verifies that all referenced environment variables are documented.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from cathedral_keeper.models import Evidence, Finding, clamp_snippet, normalize_path
from cathedral_keeper.path_glob import matches_any
from cathedral_keeper.python_imports import read_text_best_effort


def check_env_parity(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
) -> List[Finding]:
    inner_cfg = cfg.get("config") or cfg

    env_docs = list(inner_cfg.get("env_docs") or [".env.example"])
    flag_conditional = bool(inner_cfg.get("flag_conditional_env", True))
    ignore_keys = set(str(k).upper() for k in (inner_cfg.get("ignore_keys") or [
        "PATH", "HOME", "USER", "PYTHONPATH",
    ]))

    root_resolved = root.resolve()
    findings: List[Finding] = []

    # Phase 1: Collect all env var keys referenced in code
    code_keys: Dict[str, List[_EnvRef]] = {}  # key -> list of references
    for f in files:
        try:
            rel = normalize_path(str(f.resolve().relative_to(root_resolved)))
        except ValueError:
            rel = normalize_path(str(f))
        source = read_text_best_effort(f)
        if not source.strip():
            continue

        refs = _find_env_references(source, rel)
        for ref in refs:
            if ref.key.upper() not in ignore_keys:
                code_keys.setdefault(ref.key, []).append(ref)

    # Phase 2: Collect documented env vars from env docs
    doc_keys: Set[str] = set()
    for doc_rel in env_docs:
        doc_path = root / doc_rel
        if doc_path.exists():
            doc_keys.update(_parse_env_doc(doc_path))

    # Phase 3: Flag conditional env branching
    if flag_conditional:
        for f in files:
            try:
                rel = normalize_path(str(f.resolve().relative_to(root_resolved)))
            except ValueError:
                rel = normalize_path(str(f))
            source = read_text_best_effort(f)
            findings.extend(_find_conditional_env(source, rel))

    # Phase 4: Keys in code but not in docs
    if doc_keys:  # Only if we found documentation
        for key, refs in sorted(code_keys.items()):
            if key in doc_keys or key.upper() in {dk.upper() for dk in doc_keys}:
                continue
            first = refs[0]
            findings.append(
                Finding(
                    policy_id="CK-ARCH-ENV-PARITY",
                    title=f"Undocumented env var: {key}",
                    severity="low",
                    confidence="medium",
                    why_it_matters=(
                        f"Environment variable '{key}' is referenced in code but "
                        f"not found in any env documentation file ({', '.join(env_docs)}). "
                        f"Undocumented variables are a common source of deployment failures."
                    ),
                    evidence=[
                        Evidence(
                            file=first.file,
                            line=first.line,
                            snippet=clamp_snippet(first.context),
                            note=f"Referenced in {len(refs)} location(s)",
                        )
                    ],
                    fix_options=[
                        f"Add '{key}' to {env_docs[0]} with a description and default.",
                        f"Add '{key}' to ignore_keys if it's a system variable.",
                    ],
                    verification=[f"grep -rn '{key}' --include='*.py' ."],
                    metadata={"key": key, "files": list({r.file for r in refs})},
                )
            )

    # Phase 5: Keys in docs but never referenced in code
    if doc_keys:
        all_code_keys_upper = {k.upper() for k in code_keys}
        for dk in sorted(doc_keys):
            if dk.upper() in all_code_keys_upper or dk.upper() in ignore_keys:
                continue
            findings.append(
                Finding(
                    policy_id="CK-ARCH-ENV-PARITY",
                    title=f"Dead config: {dk}",
                    severity="info",
                    confidence="low",
                    why_it_matters=(
                        f"Environment variable '{dk}' is documented but never "
                        f"referenced in any source file. Dead configuration creates "
                        f"noise and confusion during deployment."
                    ),
                    evidence=[
                        Evidence(
                            file=env_docs[0],
                            line=0,
                            snippet=clamp_snippet(f"{dk}=..."),
                            note="Documented but not referenced in code",
                        )
                    ],
                    fix_options=[
                        f"Remove '{dk}' from {env_docs[0]} if it is no longer needed.",
                        "If it's used by an external tool, add a comment documenting that.",
                    ],
                    verification=[f"grep -rn '{dk}' --include='*.py' ."],
                    metadata={"key": dk},
                )
            )

    return findings


# ── data containers ────────────────────────────────────────────────

class _EnvRef:
    __slots__ = ("file", "line", "key", "context")

    def __init__(self, file: str, line: int, key: str, context: str) -> None:
        self.file = file
        self.line = line
        self.key = key
        self.context = context


# ── env var detection ──────────────────────────────────────────────

_ENV_KEY_PATTERNS = [
    re.compile(r'''os\.environ\s*\[\s*['"]([^'"]+)['"]\s*\]'''),
    re.compile(r'''os\.environ\.get\s*\(\s*['"]([^'"]+)['"]'''),
    re.compile(r'''os\.getenv\s*\(\s*['"]([^'"]+)['"]'''),
]


def _find_env_references(source: str, rel_path: str) -> List[_EnvRef]:
    refs: List[_EnvRef] = []
    for i, line_text in enumerate(source.splitlines(), start=1):
        for pat in _ENV_KEY_PATTERNS:
            for m in pat.finditer(line_text):
                refs.append(_EnvRef(
                    file=rel_path, line=i, key=m.group(1),
                    context=line_text.strip(),
                ))
    return refs


# ── conditional env detection ──────────────────────────────────────

_CONDITIONAL_PATTERNS = [
    re.compile(r'''if\s+.*os\.environ\.get\s*\('''),
    re.compile(r'''if\s+.*os\.getenv\s*\('''),
    re.compile(r'''if\s+.*os\.environ\s*\['''),
    re.compile(r'''if\s+.*settings\.\w*[Ee][Nn][Vv]\w*\s*=='''),
    re.compile(r'''if\s+(?:not\s+)?(?:DEBUG|PRODUCTION|TESTING|DEVELOPMENT)\s*:'''),
    re.compile(r'''if\s+(?:not\s+)?settings\.DEBUG\s*:'''),
]


def _find_conditional_env(source: str, rel_path: str) -> List[Finding]:
    findings: List[Finding] = []
    for i, line_text in enumerate(source.splitlines(), start=1):
        stripped = line_text.strip()
        for pat in _CONDITIONAL_PATTERNS:
            if pat.search(stripped):
                findings.append(
                    Finding(
                        policy_id="CK-ARCH-ENV-PARITY",
                        title=f"Environment-conditional branch: {rel_path}:{i}",
                        severity="info",
                        confidence="medium",
                        why_it_matters=(
                            "Environment-conditional code paths behave differently "
                            "across environments. This is a common root cause of "
                            "'works in QA, breaks in production' failures."
                        ),
                        evidence=[
                            Evidence(
                                file=rel_path,
                                line=i,
                                snippet=clamp_snippet(stripped),
                                note="Environment-dependent branching",
                            )
                        ],
                        fix_options=[
                            "Ensure all env-conditional paths are tested in CI for each target environment.",
                            "Consider using a strategy/configuration pattern instead of branching.",
                        ],
                        verification=[f"grep -n 'if.*environ\\|if.*DEBUG\\|if.*PRODUCTION' {rel_path}"],
                        metadata={"file": rel_path, "line": i},
                    )
                )
                break  # one finding per line
    return findings


# ── env doc parsing ────────────────────────────────────────────────

def _parse_env_doc(path: Path) -> Set[str]:
    """Parse a .env.example or similar file and extract variable names."""
    keys: Set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return keys

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match KEY=value or KEY= or just KEY (bare declaration)
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        if m:
            keys.add(m.group(1))
    return keys
