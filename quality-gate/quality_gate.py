#!/usr/bin/env python3
"""
Quality Gate - Portable Code Quality Enforcement System
========================================================
Drop this into any codebase for instant quality enforcement.

Usage:
    python quality_gate.py                    # Check all files
    python quality_gate.py --staged           # Check staged files only (for pre-commit)
    python quality_gate.py --report           # Generate detailed report
    python quality_gate.py --strict           # Fail on warnings too
    python quality_gate.py --min-score 90     # Enforce stricter PRS threshold
    python quality_gate.py --no-prs           # Disable PRS scoring gate
    python quality_gate.py path/to/file.py    # Check specific file

Exit codes:
    0 - All checks passed
    1 - Errors found (blocks commit/merge)
    2 - Warnings found (--strict mode only)
"""

import argparse
import ast
import contextlib
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

try:  # optional modular rules (keeps CLI stable while allowing gradual refactor)
    from qg.context import RuleContext
    from qg.rules_phase1 import apply as apply_phase1_rules
    from qg.rules_phase2 import apply as apply_phase2_rules
    from qg.rules_tests import apply as apply_test_rules
except Exception:  # pragma: no cover
    RuleContext = None  # type: ignore[assignment]
    apply_phase1_rules = None  # type: ignore[assignment]
    apply_phase2_rules = None  # type: ignore[assignment]
    apply_test_rules = None  # type: ignore[assignment]

try:  # technology-pack checks (python, fastapi, langchain, ai/llm, ai smells)
    from qg.checks_python import check_python_patterns
    from qg.checks_fastapi import check_fastapi_patterns
    from qg.checks_langchain import check_langchain_patterns
    from qg.checks_ai_smells import check_ai_smell_patterns
    from qg.checks_ai_llm import check_ai_llm_patterns
except Exception:  # pragma: no cover
    check_python_patterns = None  # type: ignore[assignment]
    check_fastapi_patterns = None  # type: ignore[assignment]
    check_langchain_patterns = None  # type: ignore[assignment]
    check_ai_smell_patterns = None  # type: ignore[assignment]
    check_ai_llm_patterns = None  # type: ignore[assignment]

try:  # Phase 2-3 technology packs (neo4j, mongodb, databases, performance, sqlalchemy, docparse, nextjs, security)
    from qg.checks_neo4j import check_neo4j_patterns
    from qg.checks_mongodb import check_mongodb_patterns
    from qg.checks_databases import check_database_patterns
    from qg.checks_performance import check_performance_patterns
    from qg.checks_sqlalchemy import check_sqlalchemy_patterns
    from qg.checks_docparse import check_docparse_patterns
    from qg.checks_nextjs import check_nextjs_patterns
    from qg.checks_security import check_security_patterns
except Exception:  # pragma: no cover
    check_neo4j_patterns = None  # type: ignore[assignment]
    check_mongodb_patterns = None  # type: ignore[assignment]
    check_database_patterns = None  # type: ignore[assignment]
    check_performance_patterns = None  # type: ignore[assignment]
    check_sqlalchemy_patterns = None  # type: ignore[assignment]
    check_docparse_patterns = None  # type: ignore[assignment]
    check_nextjs_patterns = None  # type: ignore[assignment]
    check_security_patterns = None  # type: ignore[assignment]

try:  # Phase 3 packs (observability, UX error handling)
    from qg.checks_observability import check_observability_patterns
    from qg.checks_ux_errors import check_ux_error_patterns
except Exception:  # pragma: no cover
    check_observability_patterns = None  # type: ignore[assignment]
    check_ux_error_patterns = None  # type: ignore[assignment]

try:  # Phase 4 packs (agentic AI safety)
    from qg.checks_agent_loops import check_agent_loop_safety
    from qg.checks_llm_output_safety import check_llm_output_safety
except Exception:  # pragma: no cover
    check_agent_loop_safety = None  # type: ignore[assignment]
    check_llm_output_safety = None  # type: ignore[assignment]

try:  # PRS veto engine
    from qg.prs_engine import should_veto, compute_bprs, DEFAULT_VETO_RULES
    HAS_PRS_VETO = True
except Exception:  # pragma: no cover
    HAS_PRS_VETO = False

# ============================================================================
# CONFIGURATION
# ============================================================================

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class Issue:
    file: str
    line: int
    column: int
    rule: str
    severity: Severity
    message: str
    code_snippet: str = ""
    suggestion: str = ""

@dataclass
class CheckResult:
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

# Default config if no config file found
DEFAULT_CONFIG = {
    "paths": {
        # If empty, we check all tracked code files (git ls-files) by default.
        "include": [],
        "exclude": [
            "**/node_modules/**",
            "**/dist/**",
            "**/build/**",
            "**/.next/**",
            "**/.git/**",
            "**/quality-gate/**",
            "**/__pycache__/**",
            "**/.pytest_cache/**",
            "**/.venv/**",
            "**/venv*/**",
            "**/site-packages/**",
        ],
    },
    "rules": {
        "file_size": {"enabled": True, "max_lines": 800, "warning_lines": 500, "severity": "error"},
        "function_size": {"enabled": True, "max_lines": 50, "severity": "error"},
        "no_todo_fixme": {"enabled": True, "severity": "error"},
        "no_debug_statements": {"enabled": True, "severity": "error"},
        "no_type_escape": {"enabled": True, "severity": "error"},
        "no_silent_catch": {"enabled": True, "severity": "error"},
    },
    "prs": {
        "enabled": True,
        "min_score": 85,
        "error_weight": 10,
        "warning_weight": 2,
        "_note": "PRS = 100 - (errors*10) - (warnings*2) per Lead2Dev QG-02.",
    },
    "thresholds": {"error_count": 0, "warning_count": 10},
}

# ============================================================================
# CORE ENGINE
# ============================================================================

def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Merge override into base recursively.

    - dict values merge recursively
    - list/scalar values replace
    """
    out: dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _parse_severity(value: str | None, *, default: Severity) -> Severity:
    if not value:
        return default
    v = str(value).strip().lower()
    if v == "warning":
        return Severity.WARNING
    if v == "info":
        return Severity.INFO
    return Severity.ERROR


def _find_git_root(start: Path) -> Path | None:
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _git_cmd(git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"safe.directory={git_root}", "-C", str(git_root), *args],
        capture_output=True,
        text=True,
    )


class QualityGate:
    def __init__(
        self,
        config_path: str | None = None,
        root_dir: str | None = None,
        *,
        quiet: bool = False,
    ):
        script_dir = Path(__file__).resolve().parent
        default_root = script_dir.parent  # <repo>/quality-gate/quality_gate.py -> <repo>/
        self.root_dir = Path(root_dir).resolve() if root_dir else default_root
        self.git_root = _find_git_root(self.root_dir) or _find_git_root(Path.cwd())
        self._git_prefix = (
            os.path.relpath(self.root_dir, self.git_root).replace("\\", "/") if self.git_root else "."
        )
        self._quiet = quiet
        self.config = self._load_config(config_path)
        self.issues: list[Issue] = []
        self.stats = defaultdict(int)
        self.file_prs: dict[str, dict[str, Any]] = {}

    def _load_config(self, config_path: str | None) -> dict:
        """Load configuration from file or use defaults."""
        script_dir = Path(__file__).resolve().parent

        merged: dict[str, Any] = dict(DEFAULT_CONFIG)
        sources: list[Path] = []

        # Priority: defaults < quality-gate.config.json (portable) < .quality-gate.json (repo override)
        defaults_path = script_dir / "quality-gate.config.json"
        if defaults_path.exists():
            sources.append(defaults_path)

        root_config = self.root_dir / "quality-gate.config.json"
        if root_config.exists() and root_config.resolve() != defaults_path.resolve():
            sources.append(root_config)

        root_override = self.root_dir / ".quality-gate.json"
        if root_override.exists():
            sources.append(root_override)

        if config_path:
            p = Path(config_path)
            if p.exists():
                sources.append(p)

        for src in sources:
            try:
                config = json.loads(src.read_text(encoding="utf-8"))
            except Exception as e:
                raise RuntimeError(f"Failed to read quality gate config: {src}: {e}") from e
            merged = _deep_merge(merged, config)

        if not self._quiet:
            if sources:
                print("[QualityGate] Config sources:")
                for s in sources:
                    print(f"  - {s}")
            else:
                print("[QualityGate] No config found, using defaults")

        return merged

    def _should_check_file(self, file_path: Path, *, explicit: bool = False) -> bool:
        """Determine if file should be checked based on include/exclude patterns."""
        try:
            rel_path = str(file_path.relative_to(self.root_dir)).replace("\\", "/")
        except ValueError:
            # Path is not relative to root_dir, use as-is
            rel_path = str(file_path).replace("\\", "/")

        # Check excludes first
        for pattern in self.config.get("paths", {}).get("exclude", []):
            pat = str(pattern or "").replace("\\", "/").strip()
            if not pat:
                continue
            if fnmatch.fnmatch(rel_path, pat):
                return False
            if pat.endswith("/"):
                needle = pat.strip("/")
                if needle and f"/{needle}/" in f"/{rel_path}/":
                    return False

        # Check includes
        includes = self.config.get("paths", {}).get("include", [])
        if explicit or not includes:
            return True

        for pattern in includes:
            pat = str(pattern or "").replace("\\", "/").strip()
            if not pat:
                continue
            if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(rel_path, pat + "*") or rel_path.startswith(pat):
                return True

        return False

    def _safe_is_file(self, path: Path) -> bool:
        """Check if path is a file, handling Windows symlink errors."""
        try:
            return path.is_file()
        except OSError:
            return False

    def _get_file_extension(self, file_path: Path) -> str:
        """Get file extension for language detection."""
        return file_path.suffix.lower()

    def _get_language(self, file_path: Path) -> str:
        """Detect language from file extension."""
        ext_map = {
            '.py': 'python',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
        }
        return ext_map.get(self._get_file_extension(file_path), 'unknown')

    @staticmethod
    def _is_test_path(file_path: Path) -> bool:
        rel = str(file_path).replace("\\", "/").lower()
        name = file_path.name.lower()
        return (
            "/tests/" in rel
            or "/test/" in rel
            or rel.startswith("tests/")
            or rel.startswith("test/")
            or name.startswith("test_")
            or name.endswith("_test.py")
            or name.endswith(".spec.ts")
            or name.endswith(".spec.tsx")
            or name.endswith(".test.ts")
            or name.endswith(".test.tsx")
            or name.endswith(".spec.js")
            or name.endswith(".test.js")
        )

    def _add_issue(
        self,
        file: str,
        line: int,
        rule: str,
        severity: Severity | str,
        message: str,
        column: int = 0,
        snippet: str = "",
        suggestion: str = "",
    ):
        """Add an issue to the collection."""
        with contextlib.suppress(ValueError):
            file = os.path.relpath(str(file), str(self.root_dir))

        if isinstance(severity, str):
            severity_raw = severity.strip().lower()
            severity = next(
                (s for s in Severity if s.value == severity_raw or s.name.lower() == severity_raw),
                Severity.WARNING,
            )

        self.issues.append(Issue(
            file=file,
            line=line,
            column=column,
            rule=rule,
            severity=severity,
            message=message,
            code_snippet=snippet,
            suggestion=suggestion
        ))
        self.stats[f"{severity.value}_{rule}"] += 1
        self.stats[severity.value] += 1

    # ========================================================================
    # RULE IMPLEMENTATIONS
    # ========================================================================

    def check_file_size(self, file_path: Path, lines: list[str]) -> None:
        """Check if file exceeds maximum line count."""
        rule_config = self.config.get("rules", {}).get("file_size", {})
        if not rule_config.get("enabled", True):
            return

        max_lines = rule_config.get("max_lines", 500)
        warning_lines = rule_config.get("warning_lines", 300)
        exceptions = rule_config.get("exceptions", [])

        # Check exceptions
        for pattern in exceptions:
            if fnmatch.fnmatch(file_path.name, pattern):
                return

        line_count = len(lines)

        if line_count > max_lines:
            self._add_issue(
                file=str(file_path),
                line=1,
                rule="file_size",
                severity=Severity.ERROR,
                message=f"File has {line_count} lines (max: {max_lines}). Split into smaller modules.",
                suggestion="Extract logical sections into separate files/modules."
            )
        elif line_count > warning_lines:
            self._add_issue(
                file=str(file_path),
                line=1,
                rule="file_size",
                severity=Severity.WARNING,
                message=f"File has {line_count} lines (warning threshold: {warning_lines}).",
                suggestion="Consider refactoring before it grows further."
            )

    def check_function_size(self, file_path: Path, lines: list[str]) -> None:
        """Check if any function exceeds maximum line count."""
        rule_config = self.config.get("rules", {}).get("function_size", {})
        if not rule_config.get("enabled", True):
            return

        language = self._get_language(file_path)
        max_lines_default = int(rule_config.get("max_lines", 50) or 50)
        max_lines_by_language = rule_config.get("max_lines_by_language", {})
        if isinstance(max_lines_by_language, dict):
            max_lines = int(max_lines_by_language.get(language, max_lines_default) or max_lines_default)
        else:
            max_lines = max_lines_default

        python_pattern = r"^(\s*)(def|async def)\s+(\w+)"
        ts_function_pattern = r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        ts_arrow_pattern = r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
        js_function_pattern = r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"
        js_arrow_pattern = r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"

        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)

        if language == "python":
            content = "\n".join(lines)
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                tree = None

            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    start = int(getattr(node, "lineno", 1) or 1)
                    end = int(getattr(node, "end_lineno", start) or start)
                    length = (end - start) + 1
                    if length > max_lines:
                        self._add_issue(
                            file=str(file_path),
                            line=start,
                            rule="function_size",
                            severity=severity,
                            message=f"Function '{node.name}' is {length} lines (max: {max_lines}).",
                            suggestion="Extract parts into smaller helper functions.",
                        )
                return

            stack: list[tuple[int, str, int]] = []

            def _indent_len(value: str) -> int:
                return len(re.match(r"^(\s*)", value).group(1))  # type: ignore[union-attr]

            def _close_until(indent: int, end_line: int) -> None:
                while stack and indent <= stack[-1][2]:
                    start, name, _ = stack.pop()
                    length = (end_line - start) + 1
                    if length > max_lines:
                        self._add_issue(
                            file=str(file_path),
                            line=start,
                            rule="function_size",
                            severity=severity,
                            message=f"Function '{name}' is {length} lines (max: {max_lines}).",
                            suggestion="Extract parts into smaller helper functions.",
                        )

            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                indent = _indent_len(line)
                if stack and indent <= stack[-1][2] and not line.lstrip().startswith("@"):
                    _close_until(indent, i - 1)

                match = re.match(python_pattern, line)
                if match:
                    name = match.group(3) if match.lastindex and match.lastindex >= 3 else "anonymous"
                    stack.append((i, name, len(match.group(1))))

            _close_until(0, len(lines))
            return

        if language not in {"typescript", "javascript"}:
            return

        function_pattern = ts_function_pattern if language == "typescript" else js_function_pattern
        arrow_pattern = ts_arrow_pattern if language == "typescript" else js_arrow_pattern

        func_start: int | None = None
        func_name: str | None = None
        brace_depth = 0
        saw_open_brace = False

        for i, line in enumerate(lines, 1):
            if func_start is None:
                match = re.match(function_pattern, line) or re.match(arrow_pattern, line)
                if match:
                    func_start = i
                    func_name = match.group(1) if match.lastindex and match.lastindex >= 1 else "anonymous"
                    brace_depth = 0
                    saw_open_brace = False

            if func_start is None:
                continue

            brace_depth += line.count("{")
            brace_depth -= line.count("}")
            if "{" in line:
                saw_open_brace = True

            if saw_open_brace and brace_depth <= 0:
                length = (i - func_start) + 1
                if length > max_lines:
                    self._add_issue(
                        file=str(file_path),
                        line=func_start,
                        rule="function_size",
                        severity=severity,
                        message=f"Function '{func_name}' is {length} lines (max: {max_lines}).",
                        suggestion="Extract parts into smaller helper functions.",
                    )
                func_start = None
                func_name = None
                brace_depth = 0
                saw_open_brace = False

    def check_no_todo_fixme(self, file_path: Path, lines: list[str]) -> None:
        """Check for TODO/FIXME comments without issue links."""
        rule_config = self.config.get("rules", {}).get("no_todo_fixme", {})
        if not rule_config.get("enabled", True):
            return

        patterns = rule_config.get("patterns", ["TODO", "FIXME", "XXX", "HACK", "BUG"])
        allow_with_issue = rule_config.get("allow_with_issue", True)
        issue_pattern = rule_config.get("issue_pattern", r"(TODO|FIXME|XXX|HACK|BUG)\s*\(#\d+\)")
        language = self._get_language(file_path)

        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)

        in_block_comment = False
        for i, line in enumerate(lines, 1):
            comment = ""
            if language == "python":
                idx = line.find("#")
                comment = line[idx + 1 :] if idx >= 0 else ""
            elif language in {"typescript", "javascript"}:
                if in_block_comment:
                    comment = line
                    if "*/" in line:
                        in_block_comment = False
                else:
                    idx_line = line.find("//")
                    idx_block = line.find("/*")
                    idx = -1
                    if idx_line >= 0 and idx_block >= 0:
                        idx = min(idx_line, idx_block)
                    else:
                        idx = idx_line if idx_line >= 0 else idx_block

                    if idx >= 0:
                        comment = line[idx + 2 :]
                        if idx_block >= 0 and idx == idx_block and "*/" not in comment:
                            in_block_comment = True

            if not comment.strip():
                continue

            upper = comment.upper()
            for pattern in patterns:
                token = re.compile(rf"\b{re.escape(pattern)}\b")
                if token.search(upper):
                    # Check if it has an issue link
                    if allow_with_issue and re.search(issue_pattern, line, re.IGNORECASE):
                        continue

                    self._add_issue(
                        file=str(file_path),
                        line=i,
                        rule="no_todo_fixme",
                        severity=severity,
                        message=f"Found '{pattern}'. Either fix it or link to an issue.",
                        snippet=line.strip()[:100],
                        suggestion=f"Change to: {pattern}(#123): description"
                    )

    def check_no_debug_statements(self, file_path: Path, lines: list[str]) -> None:
        """Check for debug statements that shouldn't be committed."""
        rule_config = self.config.get("rules", {}).get("no_debug_statements", {})
        if not rule_config.get("enabled", True):
            return

        language = self._get_language(file_path)
        patterns_config = rule_config.get("patterns", {})
        patterns = patterns_config.get(language, [])
        exceptions = rule_config.get("exceptions", ["console.error"])

        # Default patterns if not configured
        if not patterns:
            if language == 'python':
                patterns = ["breakpoint()", "pdb.set_trace"]
            elif language in ('typescript', 'javascript'):
                patterns = ["console.log", "console.debug", "debugger"]

        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)
        for i, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('//'):
                continue

            for pattern in patterns:
                if pattern in line:
                    # Check exceptions
                    is_exception = any(exc in line for exc in exceptions)
                    if not is_exception:
                        self._add_issue(
                            file=str(file_path),
                            line=i,
                            rule="no_debug_statements",
                            severity=severity,
                            message=f"Debug statement found: '{pattern}'",
                            snippet=line.strip()[:100],
                            suggestion="Remove before committing."
                        )

    def check_no_type_escape(self, file_path: Path, lines: list[str]) -> None:
        """Check for type system escapes (any, ts-ignore, etc.)."""
        rule_config = self.config.get("rules", {}).get("no_type_escape", {})
        if not rule_config.get("enabled", True):
            return

        language = self._get_language(file_path)
        patterns_config = rule_config.get("patterns", {})
        patterns = patterns_config.get(language, [])

        # Default patterns
        if not patterns:
            if language == 'typescript':
                patterns = ["as any", ": any", "@ts-ignore", "@ts-nocheck", "@ts-expect-error"]
            elif language == 'python':
                patterns = ["# type: ignore", "typing.Any", ": Any"]

        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)
        for i, line in enumerate(lines, 1):
            for pattern in patterns:
                if pattern in line:
                    self._add_issue(
                        file=str(file_path),
                        line=i,
                        rule="no_type_escape",
                        severity=severity,
                        message=f"Type escape found: '{pattern}'",
                        snippet=line.strip()[:100],
                        suggestion="Fix the type properly instead of escaping."
                    )

    def check_no_silent_catch(self, file_path: Path, content: str, lines: list[str]) -> None:
        """Check for empty catch blocks or except: pass."""
        rule_config = self.config.get("rules", {}).get("no_silent_catch", {})
        if not rule_config.get("enabled", True):
            return

        language = self._get_language(file_path)
        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)

        # Python: except: pass or except Exception: pass
        if language == 'python':
            pattern = r'except\s*(\w+)?:\s*\n\s*pass\b'
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count('\n') + 1
                self._add_issue(
                    file=str(file_path),
                    line=line_num,
                    rule="no_silent_catch",
                    severity=severity,
                    message="Silent exception catch (except: pass). Errors are being swallowed.",
                    suggestion="Log the error or handle it properly."
                )

        # JavaScript/TypeScript: catch(e) {}
        elif language in ('javascript', 'typescript'):
            pattern = r'catch\s*\([^)]*\)\s*\{\s*\}'
            for match in re.finditer(pattern, content):
                line_num = content[:match.start()].count('\n') + 1
                self._add_issue(
                    file=str(file_path),
                    line=line_num,
                    rule="no_silent_catch",
                    severity=severity,
                    message="Empty catch block. Errors are being swallowed.",
                    suggestion="Log the error or handle it properly."
                )

    def check_no_hardcoded_secrets(self, file_path: Path, lines: list[str]) -> None:
        """Check for hardcoded secrets/credentials."""
        rule_config = self.config.get("rules", {}).get("no_hardcoded_secrets", {})
        if not rule_config.get("enabled", True):
            return

        patterns = [
            (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\'][^"\']{8,}["\']', "password"),
            (r'(?i)(api_key|apikey|api-key)\s*[=:]\s*["\'][^"\']{16,}["\']', "API key"),
            (r'(?i)(secret|secret_key)\s*[=:]\s*["\'][^"\']{16,}["\']', "secret"),
            (r'(?i)(token|auth_token|access_token)\s*[=:]\s*["\'][A-Za-z0-9_-]{20,}["\']', "token"),
            (r'-----BEGIN (RSA |EC )?PRIVATE KEY-----', "private key"),
        ]

        exceptions = rule_config.get("exceptions", ["test", "example", "placeholder", '""', "''"])
        severity = _parse_severity(rule_config.get("severity"), default=Severity.ERROR)

        for i, line in enumerate(lines, 1):
            for pattern, secret_type in patterns:
                if re.search(pattern, line):
                    # Check exceptions
                    is_exception = any(exc in line.lower() for exc in exceptions)
                    if not is_exception:
                        self._add_issue(
                            file=str(file_path),
                            line=i,
                            rule="no_hardcoded_secrets",
                            severity=severity,
                            message=f"Potential hardcoded {secret_type} found.",
                            snippet=line.strip()[:50] + "...",
                            suggestion="Use environment variables instead."
                    )

    def check_noqa_ann001(self, file_path: Path, lines: list[str]) -> None:
        """Check for ANN001 suppressions in test code."""
        rule_config = self.config.get("rules", {}).get("noqa_ann001", {})
        if not rule_config.get("enabled", False):
            return
        if self._get_language(file_path) != "python":
            return
        if not self._is_test_path(file_path):
            return

        severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)
        for i, line in enumerate(lines, 1):
            if "noqa" not in line:
                continue
            if "ANN001" not in line:
                continue
            self._add_issue(
                file=str(file_path),
                line=i,
                rule="noqa_ann001",
                severity=severity,
                message="Avoid `# noqa: ANN001` in tests; add a proper type annotation instead.",
                snippet=line.strip()[:120],
                suggestion="Add a real annotation (or refactor the helper) instead of suppressing.",
            )

    def check_duplicate_class_defs(self, file_path: Path, lines: list[str]) -> None:
        """Warn on repeated class definitions in a single test file."""
        rule_config = self.config.get("rules", {}).get("duplicate_class_defs", {})
        if not rule_config.get("enabled", False):
            return
        if self._get_language(file_path) != "python":
            return
        if not self._is_test_path(file_path):
            return

        severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)
        seen: dict[str, int] = {}
        for i, line in enumerate(lines, 1):
            match = re.match(r"^\s*class\s+(\w+)\b", line)
            if not match:
                continue
            name = match.group(1)
            if name in seen:
                self._add_issue(
                    file=str(file_path),
                    line=i,
                    rule="duplicate_class_defs",
                    severity=severity,
                    message=f"Class '{name}' redefined in the same file (previous at line {seen[name]}).",
                    snippet=line.strip()[:120],
                    suggestion="Extract shared test helpers to module scope or a fixture.",
                )
            else:
                seen[name] = i

    def check_classvar_in_tests(self, file_path: Path, lines: list[str]) -> None:
        """Warn on `ClassVar` state in test code (often used for cross-test coordination)."""
        rule_config = self.config.get("rules", {}).get("classvar_in_tests", {})
        if not rule_config.get("enabled", False):
            return
        if self._get_language(file_path) != "python":
            return
        if not self._is_test_path(file_path):
            return

        severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)
        for i, line in enumerate(lines, 1):
            if "ClassVar" not in line:
                continue
            if "=" not in line:
                continue
            self._add_issue(
                file=str(file_path),
                line=i,
                rule="classvar_in_tests",
                severity=severity,
                message="Avoid `ClassVar` state in tests; prefer fixtures or closure-based capture.",
                snippet=line.strip()[:120],
                suggestion="Replace cross-test coordination state with a fixture or per-test helper.",
            )

    def check_test_parametrisation(self, file_path: Path, lines: list[str]) -> None:
        """Flag near-duplicate python test functions that should use parametrization."""
        rule_config = self.config.get("rules", {}).get("test_parametrisation", {})
        if not rule_config.get("enabled", False):
            return
        if self._get_language(file_path) != "python":
            return
        if not self._is_test_path(file_path):
            return

        min_similar = int(rule_config.get("min_similar_tests", 3) or 3)
        severity = _parse_severity(rule_config.get("severity"), default=Severity.INFO)

        tests: list[tuple[str, int]] = []
        for i, line in enumerate(lines, 1):
            match = re.match(r"^\s*def\s+(test_\w+)\s*\(", line)
            if match:
                tests.append((match.group(1), i))

        if not tests:
            return

        prefixes: Counter[str] = Counter()
        first_line_by_prefix: dict[str, int] = {}
        for name, line_no in tests:
            prefix = re.sub(r"_(\d+|success|failure|error|valid|invalid)$", "", name)
            prefixes[prefix] += 1
            first_line_by_prefix.setdefault(prefix, line_no)

        for prefix, count in prefixes.items():
            if count < min_similar:
                continue
            self._add_issue(
                file=str(file_path),
                line=first_line_by_prefix.get(prefix, 1),
                rule="test_parametrisation",
                severity=severity,
                message=(
                    f"Found {count} similar tests starting with '{prefix}'. "
                    "Consider pytest.mark.parametrize."
                ),
                suggestion="Consolidate into a parametrised test to reduce duplication.",
            )

    def check_import_count(self, file_path: Path, lines: list[str]) -> None:
        """Warn/info when a module has too many imports (often indicates SRP drift)."""
        rule_config = self.config.get("rules", {}).get("import_count", {})
        if not rule_config.get("enabled", False):
            return

        max_imports = int(rule_config.get("max_imports", 20) or 20)
        severity = _parse_severity(rule_config.get("severity"), default=Severity.INFO)
        language = self._get_language(file_path)

        count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue
            if language == "python":
                if stripped.startswith("import ") or stripped.startswith("from "):
                    count += 1
            elif language in {"typescript", "javascript"} and stripped.startswith("import "):
                count += 1

        if count > max_imports:
            self._add_issue(
                file=str(file_path),
                line=1,
                rule="import_count",
                severity=severity,
                message=f"Module has {count} import statements (max: {max_imports}).",
                suggestion="Consider splitting responsibilities or consolidating imports.",
            )

    def check_max_complexity(self, file_path: Path, lines: list[str]) -> None:
        """Check cyclomatic complexity (simplified check based on branching)."""
        rule_config = self.config.get("rules", {}).get("max_complexity", {})
        if not rule_config.get("enabled", True):
            return

        max_complexity = rule_config.get("cyclomatic_max", 10)
        language = self._get_language(file_path)

        if language == "python":
            content = "\n".join(lines)
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                return

            severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)

            def _complexity(node: ast.AST) -> int:
                score = 1
                for child in ast.walk(node):
                    if isinstance(
                        child,
                        (
                            ast.If,
                            ast.For,
                            ast.AsyncFor,
                            ast.While,
                            ast.With,
                            ast.AsyncWith,
                            ast.Try,
                            ast.ExceptHandler,
                            ast.IfExp,
                        ),
                    ):
                        score += 1
                    elif isinstance(child, ast.BoolOp):
                        score += max(0, len(child.values) - 1)
                    elif isinstance(child, ast.Match):
                        score += len(child.cases)
                return score

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                c = _complexity(node)
                if c > max_complexity:
                    start = int(getattr(node, "lineno", 1) or 1)
                    self._add_issue(
                        file=str(file_path),
                        line=start,
                        rule="max_complexity",
                        severity=severity,
                        message=f"Function '{node.name}' has complexity {c} (max: {max_complexity}).",
                        suggestion="Simplify by extracting conditions or using early returns.",
                    )
            return

        # Count branching keywords
        branch_keywords = {
            'python': ['if ', 'elif ', 'for ', 'while ', 'except ', 'and ', 'or ', 'case '],
            'typescript': ['if ', 'else if ', 'for ', 'while ', 'catch ', '&& ', '|| ', 'case ', '? '],
            'javascript': ['if ', 'else if ', 'for ', 'while ', 'catch ', '&& ', '|| ', 'case ', '? '],
        }

        keywords = branch_keywords.get(language, [])
        if not keywords:
            return

        severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)

        # Simple per-function complexity tracking
        current_func = None
        func_start = 0
        complexity = 1

        def _match_function_name(line: str) -> str | None:
            if language in {"typescript", "javascript"}:
                match = re.match(
                    r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\b", line
                )
                if match:
                    return match.group(1)

                match = re.match(
                    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(.+)$", line
                )
                if not match:
                    return None
                rhs = match.group(2).strip()
                if "=>" in rhs:
                    return match.group(1)
                if re.match(r"^(?:async\s+)?function\b", rhs):
                    return match.group(1)
                return None

            return None

        for i, line in enumerate(lines, 1):
            func_name = _match_function_name(line)
            if func_name:
                # Check previous function
                if current_func and complexity > max_complexity:
                    self._add_issue(
                        file=str(file_path),
                        line=func_start,
                        rule="max_complexity",
                        severity=severity,
                        message=f"Function '{current_func}' has complexity {complexity} (max: {max_complexity}).",
                        suggestion="Simplify by extracting conditions or using early returns."
                    )

                current_func = func_name
                func_start = i
                complexity = 1
            else:
                for kw in keywords:
                    complexity += line.count(kw)

        if current_func and complexity > max_complexity:
            self._add_issue(
                file=str(file_path),
                line=func_start,
                rule="max_complexity",
                severity=severity,
                message=f"Function '{current_func}' has complexity {complexity} (max: {max_complexity}).",
                suggestion="Simplify by extracting conditions or using early returns.",
            )

    def check_duplicate_helpers(self, all_files: dict[Path, list[str]]) -> None:
        """Detect duplicate utility functions across files."""
        rule_config = self.config.get("rules", {}).get("no_duplicate_code", {})
        if not rule_config.get("enabled", True):
            return

        # Track function definitions
        func_signatures: dict[str, list[tuple[Path, int]]] = defaultdict(list)
        severity = _parse_severity(rule_config.get("severity"), default=Severity.WARNING)

        for file_path, lines in all_files.items():
            if self._is_test_path(file_path):
                continue
            language = self._get_language(file_path)
            if language not in ('python', 'typescript', 'javascript'):
                continue

            # Extract top-level function names (avoid noisy method/inner defs).
            if language == "python":
                pattern = r'^(?P<indent>\s*)(?:async\s+def|def)\s+(?P<name>\w+)\s*\('
            else:
                pattern = (
                    r'^(?P<indent>\s*)(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)\s*\('
                    r'|^(?P<indent2>\s*)(?:export\s+)?(?:const|let|var)\s+(?P<name2>\w+)\s*=\s*(?:async\s+)?\('
                )

            skip_names = {
                "constructor",
                "render",
                "main",
                "init",
                "setup",
                "__init__",
                "__repr__",
                "__str__",
            }
            for i, line in enumerate(lines, 1):
                match = re.match(pattern, line)
                if match:
                    indent = match.group("indent") if "indent" in match.groupdict() else match.group("indent2") or ""
                    if indent and len(indent) > 0:
                        continue
                    func_name = match.group("name") if "name" in match.groupdict() and match.group("name") else match.group("name2")
                    if not func_name or func_name in skip_names:
                        continue
                    if func_name.startswith("_"):
                        continue
                    func_signatures[str(func_name)].append((file_path, i))

        # Report duplicates
        for func_name, locations in func_signatures.items():
            if len(locations) > 1:
                # Only report if in different files
                files = set(str(loc[0]) for loc in locations)
                if len(files) > 1:
                    first_loc = locations[0]
                    self._add_issue(
                        file=str(first_loc[0]),
                        line=first_loc[1],
                        rule="no_duplicate_code",
                        severity=severity,
                        message=f"Function '{func_name}' defined in {len(locations)} places.",
                        suggestion=(
                            "Extract to shared utility. Also in: "
                            + ", ".join(str(loc[0].name) for loc in locations[1:3])
                        ),
                    )

    # ========================================================================
    # MAIN EXECUTION
    # ========================================================================

    def _is_code_file(self, file_path: Path) -> bool:
        exts = self.config.get("paths", {}).get(
            "extensions", [".py", ".ts", ".tsx", ".js", ".jsx"]
        )
        try:
            ext_set = {str(e).lower() for e in exts}
        except TypeError:
            ext_set = {".py", ".ts", ".tsx", ".js", ".jsx"}
        return file_path.suffix.lower() in ext_set

    def get_files_to_check(self, paths: list[str] | None = None, staged_only: bool = False) -> list[Path]:
        """Get list of files to check."""
        if staged_only:
            if not self.git_root:
                if not self._quiet:
                    print("[QualityGate] Not a git repo; --staged requires git.")
                return []

            result = _git_cmd(self.git_root, ["diff", "--cached", "--name-only", "--diff-filter=ACM"])
            if result.returncode == 0:
                files: list[Path] = []
                for rel in result.stdout.splitlines():
                    rel = rel.strip()
                    if not rel:
                        continue
                    p = (self.git_root / rel).resolve()
                    if not p.exists():
                        continue
                    try:
                        p.relative_to(self.root_dir)
                    except ValueError:
                        continue
                    if not self._is_code_file(p):
                        continue
                    if self._should_check_file(p):
                        files.append(p)
                return files

        if paths:
            files = []
            for path in paths:
                p = Path(path)
                # Resolve relative paths robustly (allow passing repo-root-relative paths in monorepos).
                if not p.is_absolute():
                    candidate = (Path.cwd() / p).resolve()
                    p = candidate if candidate.exists() else (self.root_dir / p).resolve()
                if self._safe_is_file(p):
                    files.append(p)
                elif p.is_dir():
                    files.extend(p.rglob('*'))
            return [f for f in files if self._safe_is_file(f) and self._is_code_file(f) and self._should_check_file(f, explicit=True)]

        # Default: check all tracked code files under root_dir (preferred; stable).
        if self.git_root:
            result = _git_cmd(self.git_root, ["ls-files"])
            if result.returncode == 0:
                files: list[Path] = []
                for rel in result.stdout.splitlines():
                    rel = rel.strip()
                    if not rel:
                        continue
                    p = (self.git_root / rel).resolve()
                    if not p.exists() or not self._safe_is_file(p):
                        continue
                    try:
                        p.relative_to(self.root_dir)
                    except ValueError:
                        continue
                    if not self._is_code_file(p):
                        continue
                    if self._should_check_file(p):
                        files.append(p)
                return files

        # Fallback: check all included paths via filesystem walk.
        files: list[Path] = []
        for include_path in self.config.get("paths", {}).get("include", ["."]):
            path = self.root_dir / include_path
            if not path.exists():
                continue
            if self._safe_is_file(path):
                files.append(path)
                continue
            files.extend([p for p in path.rglob("*") if self._safe_is_file(p)])

        return [f for f in files if self._is_code_file(f) and self._should_check_file(f)]

    def check_file(self, file_path: Path) -> None:
        """Run all checks on a single file."""
        try:
            with open(file_path, encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.splitlines()
        except Exception as e:
            self._add_issue(
                file=str(file_path),
                line=0,
                rule="file_read_error",
                severity=Severity.ERROR,
                message=f"Could not read file: {e}"
            )
            return

        self.stats['files_checked'] += 1
        self.stats['lines_checked'] += len(lines)

        # Run all checks
        self.check_file_size(file_path, lines)
        self.check_function_size(file_path, lines)
        self.check_no_todo_fixme(file_path, lines)
        self.check_no_debug_statements(file_path, lines)
        self.check_no_type_escape(file_path, lines)
        self.check_no_silent_catch(file_path, content, lines)
        self.check_no_hardcoded_secrets(file_path, lines)
        self.check_max_complexity(file_path, lines)
        self.check_noqa_ann001(file_path, lines)
        self.check_duplicate_class_defs(file_path, lines)
        self.check_classvar_in_tests(file_path, lines)
        self.check_test_parametrisation(file_path, lines)
        self.check_import_count(file_path, lines)

        if RuleContext is not None:
            def _add_issue_bridge(*, severity: Any = None, **kwargs: Any) -> None:
                sev = severity
                if isinstance(sev, str):
                    sev = _parse_severity(sev, default=Severity.WARNING)
                if sev is None:
                    sev = Severity.WARNING
                if "file" not in kwargs:
                    kwargs["file"] = str(file_path)
                self._add_issue(severity=sev, **kwargs)

            ctx = RuleContext(
                file_path=file_path,
                content=content,
                lines=lines,
                language=self._get_language(file_path),
                is_test=self._is_test_path(file_path),
                config=self.config,
                add_issue=_add_issue_bridge,
            )
            if apply_phase1_rules is not None:
                apply_phase1_rules(ctx)
            if apply_phase2_rules is not None:
                apply_phase2_rules(ctx)
            if apply_test_rules is not None:
                apply_test_rules(ctx)

            # Technology-pack checks (python, fastapi, langchain, ai smells)
            if check_python_patterns is not None:
                check_python_patterns(ctx)
            if check_fastapi_patterns is not None:
                check_fastapi_patterns(ctx)
            if check_langchain_patterns is not None:
                check_langchain_patterns(ctx)
            if check_ai_smell_patterns is not None:
                check_ai_smell_patterns(ctx)

            # Phase 2-3 technology packs
            if check_neo4j_patterns is not None:
                check_neo4j_patterns(ctx)
            if check_mongodb_patterns is not None:
                check_mongodb_patterns(ctx)
            if check_database_patterns is not None:
                check_database_patterns(ctx)
            if check_performance_patterns is not None:
                check_performance_patterns(ctx)
            if check_sqlalchemy_patterns is not None:
                check_sqlalchemy_patterns(ctx)
            if check_docparse_patterns is not None:
                check_docparse_patterns(ctx)
            if check_nextjs_patterns is not None:
                check_nextjs_patterns(ctx)
            if check_security_patterns is not None:
                check_security_patterns(ctx)

            # Phase 3 packs (observability, UX error handling)
            if check_observability_patterns is not None:
                check_observability_patterns(ctx)
            if check_ux_error_patterns is not None:
                check_ux_error_patterns(ctx)

            # AI/LLM checks (uses standalone signature, not RuleContext)
            if check_ai_llm_patterns is not None:
                check_ai_llm_patterns(
                    file_path=file_path,
                    content=content,
                    lines=lines,
                    language=self._get_language(file_path),
                    config=self.config,
                    add_issue=_add_issue_bridge,
                )

            # Phase 4 packs (agentic AI safety)
            if check_agent_loop_safety is not None:
                check_agent_loop_safety(
                    file_path=file_path,
                    content=content,
                    lines=lines,
                    add_issue=_add_issue_bridge,
                )
            if check_llm_output_safety is not None:
                check_llm_output_safety(
                    file_path=file_path,
                    content=content,
                    lines=lines,
                    add_issue=_add_issue_bridge,
                )

    def run(self, paths: list[str] | None = None, staged_only: bool = False) -> CheckResult:
        """Run quality gate checks."""
        files = self.get_files_to_check(paths, staged_only)

        if not files:
            if not self._quiet:
                print("[QualityGate] No files to check.")
            return CheckResult(passed=True, stats={"files_checked": 0})

        if not self._quiet:
            print(f"[QualityGate] Checking {len(files)} files...")

        # Load all files for cross-file checks
        all_files: dict[Path, list[str]] = {}
        for file_path in files:
            try:
                with open(file_path, encoding='utf-8', errors='ignore') as f:
                    all_files[file_path] = f.read().splitlines()
            except (OSError, UnicodeDecodeError):
                continue  # skip unreadable files

        # Run per-file checks
        for file_path in files:
            self.check_file(file_path)

        # Run cross-file checks
        self.check_duplicate_helpers(all_files)

        # PRS scoring (numeric readiness gate, per file)
        prs_cfg = self.config.get("prs", {}) if isinstance(self.config.get("prs", {}), dict) else {}
        if prs_cfg.get("enabled", True):
            min_score = int(prs_cfg.get("min_score", 85) or 85)
            error_weight = float(prs_cfg.get("error_weight", 10) or 10)
            warning_weight = float(prs_cfg.get("warning_weight", 2) or 2)

            counts: dict[str, dict[str, int]] = defaultdict(lambda: {"errors": 0, "warnings": 0})
            for issue in self.issues:
                # Don't let PRS enforcement issues affect PRS scoring.
                if issue.rule == "prs_score":
                    continue
                if issue.severity == Severity.ERROR:
                    counts[issue.file]["errors"] += 1
                elif issue.severity == Severity.WARNING:
                    counts[issue.file]["warnings"] += 1

            prs_failed = 0
            for file_path in files:
                rel = os.path.relpath(str(file_path), str(self.root_dir))
                c = counts.get(rel, {"errors": 0, "warnings": 0})
                score = 100.0 - (c["errors"] * error_weight) - (c["warnings"] * warning_weight)
                score = max(0.0, min(100.0, score))

                # PRS veto: CRITICAL findings or security rules → VETOED
                vetoed = False
                if HAS_PRS_VETO:
                    file_issues = [i for i in self.issues if i.file == rel and i.rule != "prs_score"]
                    vetoed = should_veto(
                        rule_severities=[i.severity.value for i in file_issues],
                        rule_names=[i.rule for i in file_issues],
                    )

                if vetoed:
                    display = "VETOED"
                    score = 0.0
                else:
                    display = str(round(score, 1))

                self.file_prs[rel] = {
                    "score": round(score, 1),
                    "display_score": display,
                    "min_score": min_score,
                    "errors": int(c["errors"]),
                    "warnings": int(c["warnings"]),
                    "vetoed": vetoed,
                }
                if vetoed or score < float(min_score):
                    prs_failed += 1
                    label = f"PRS VETOED (critical/security finding)" if vetoed else f"PRS {score:.1f}/100 below minimum {min_score}."
                    self._add_issue(
                        file=rel,
                        line=1,
                        rule="prs_score",
                        severity=Severity.ERROR,
                        message=label,
                        suggestion="Fix critical/security findings first." if vetoed else "Fix errors/warnings in this file; split large functions/files; remove debug/todos; improve error handling.",
                    )

            self.stats["prs_files_scored"] = len(self.file_prs)
            self.stats["prs_files_failed"] = prs_failed
            self.stats["prs_min_score"] = min_score

        # Compile results
        thresholds = self.config.get("thresholds", {})
        max_errors = thresholds.get("error_count", 0)

        error_count = self.stats.get('error', 0)

        passed = error_count <= max_errors

        return CheckResult(
            passed=passed,
            issues=self.issues,
            stats=dict(self.stats)
        )

    def print_report(self, result: CheckResult, verbose: bool = False) -> None:
        """Print human-readable report."""
        print("\n" + "=" * 70)
        print("QUALITY GATE REPORT")
        print("=" * 70)

        # Summary
        print(f"\nFiles checked: {result.stats.get('files_checked', 0)}")
        print(f"Lines checked: {result.stats.get('lines_checked', 0)}")
        print(f"Errors: {result.stats.get('error', 0)}")
        print(f"Warnings: {result.stats.get('warning', 0)}")
        if "prs_files_scored" in result.stats:
            print(
                "PRS: "
                f"min={result.stats.get('prs_min_score')} "
                f"failed={result.stats.get('prs_files_failed')}/{result.stats.get('prs_files_scored')}"
            )

        if not result.issues:
            print("\n[PASSED] No issues found.")
            return

        # Group by file
        issues_by_file: dict[str, list[Issue]] = defaultdict(list)
        for issue in result.issues:
            issues_by_file[issue.file].append(issue)

        print("\n" + "-" * 70)
        print("ISSUES BY FILE")
        print("-" * 70)

        for file, issues in sorted(issues_by_file.items()):
            rel_file = os.path.relpath(file)
            print(f"\n{rel_file}:")
            for issue in sorted(issues, key=lambda x: x.line):
                icon = "[E]" if issue.severity == Severity.ERROR else "[W]"
                print(f"  {icon} Line {issue.line}: [{issue.rule}] {issue.message}")
                if verbose and issue.code_snippet:
                    print(f"      > {issue.code_snippet}")
                if verbose and issue.suggestion:
                    print(f"      Fix: {issue.suggestion}")

        print("\n" + "-" * 70)
        status = "[FAILED]" if not result.passed else "[PASSED with warnings]"
        print(f"{status}")
        print("-" * 70)

    def generate_json_report(self, result: CheckResult) -> str:
        """Generate JSON report for CI/CD integration."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "passed": result.passed,
            "stats": result.stats,
            "prs": self.file_prs,
            "issues": [
                {
                    "file": issue.file,
                    "line": issue.line,
                    "column": issue.column,
                    "rule": issue.rule,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "snippet": issue.code_snippet,
                    "suggestion": issue.suggestion
                }
                for issue in result.issues
            ]
        }
        return json.dumps(report, indent=2)


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Quality Gate - Portable Code Quality Enforcement",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('paths', nargs='*', help='Specific files or directories to check')
    parser.add_argument('--paths-from', help='Read newline-delimited paths from this file')
    parser.add_argument('--staged', action='store_true', help='Check staged files only (for pre-commit)')
    parser.add_argument('--mode', choices=['check', 'audit'], default='check', help='check=enforce, audit=report only')
    parser.add_argument('--top', type=int, default=0, help='In audit mode, print lowest PRS files (default: 0)')
    parser.add_argument('--strict', action='store_true', help='Fail on warnings too')
    parser.add_argument('--config', help='Path to config file')
    parser.add_argument('--report', action='store_true', help='Generate detailed report files')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show code snippets and suggestions')
    parser.add_argument('--root', help='Project root directory (default: parent of this quality-gate folder)')
    parser.add_argument('--no-prs', action='store_true', help='Disable PRS scoring/enforcement')
    parser.add_argument('--min-score', type=int, default=None, help='Override PRS minimum score (default: 85)')

    args = parser.parse_args()

    gate = QualityGate(config_path=args.config, root_dir=args.root, quiet=bool(args.json))
    if args.no_prs:
        gate.config.setdefault("prs", {})["enabled"] = False
    if args.min_score is not None:
        gate.config.setdefault("prs", {})["min_score"] = int(args.min_score)

    paths: list[str] = list(args.paths or [])
    if args.paths_from:
        p = Path(args.paths_from)
        raw = p.read_text(encoding="utf-8", errors="ignore")
        for line in raw.splitlines():
            line = line.strip()
            if line:
                paths.append(line)

    result = gate.run(paths=paths or None, staged_only=args.staged)

    if args.json:
        print(gate.generate_json_report(result))
    elif args.mode == "audit" and not args.verbose:
        print("QUALITY GATE AUDIT")
        print(f"Files checked: {result.stats.get('files_checked', 0)}")
        print(f"Errors: {result.stats.get('error', 0)}")
        print(f"Warnings: {result.stats.get('warning', 0)}")
        if "prs_files_scored" in result.stats:
            print(
                "PRS: "
                f"min={result.stats.get('prs_min_score')} "
                f"failed={result.stats.get('prs_files_failed')}/{result.stats.get('prs_files_scored')}"
            )
    else:
        gate.print_report(result, verbose=args.verbose)

    if args.mode == "audit" and args.top and gate.file_prs:
        ranked = sorted(gate.file_prs.items(), key=lambda kv: float(kv[1].get("score", 0.0)))
        top_n = min(int(args.top), len(ranked))
        print("\nTop highest-slop files (lowest PRS):")
        for fp, meta in ranked[:top_n]:
            print(f"  {meta.get('score')}/100  {fp}  (errors={meta.get('errors')}, warnings={meta.get('warnings')})")

    # Generate report files if requested
    if args.report:
        os.makedirs('.quality-reports', exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        with open(f'.quality-reports/report_{timestamp}.json', 'w') as f:
            f.write(gate.generate_json_report(result))
        print(f"\nReport saved to .quality-reports/report_{timestamp}.json")

    # Exit code
    if args.mode == "audit":
        sys.exit(0)
    if not result.passed:
        sys.exit(1)
    elif args.strict and result.stats.get('warning', 0) > 0:
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
