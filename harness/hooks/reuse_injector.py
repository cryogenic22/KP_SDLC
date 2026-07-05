#!/usr/bin/env python
"""PreToolUse reuse injector — deterministic "you already wrote this" hints.

Self-contained, stdlib-only (born repos do not carry quality-gate/, so this
file has no imports outside the standard library). Wired from
.claude/settings.json as:

    {"hooks": {"PreToolUse": [{"matcher": "Write|Edit", "hooks": [
        {"type": "command", "command": "python -P .harness/hooks/reuse_injector.py",
         "timeout": 15}]}]}}

Contract (Claude Code PreToolUse hook):
  * stdin: JSON {hook_event_name, tool_name, tool_input:{file_path,
    content|new_string}, cwd, ...} — read via sys.stdin.buffer + explicit
    utf-8 decode (Windows consoles default to cp1252).
  * inject: exit 0 + stdout JSON {"hookSpecificOutput": {"hookEventName":
    "PreToolUse", "permissionDecision": "allow", "additionalContext": ...}}.
  * silent: exit 0 + empty stdout.
  * FAIL-OPEN IS ABSOLUTE: every code path exits 0. Exit 2 is the PreToolUse
    block signal — an injector crash exiting 2 would deny every file write in
    the session, an unacceptable false red. This hook never blocks and never
    emits a 'deny' decision. Blocking clone enforcement is the quality gate's
    job at commit/CI, not this hook's.

Two deterministic match tiers only (no fuzzy similarity):
  TIER-1  exact body-hash clone (name-independent AST signature)
  TIER-2  same public name defined elsewhere

PARITY (load-bearing): collect_signatures() below computes the exact
signature formula of quality-gate/qg/checks_duplicates.py
(_collect_python_sigs) — same min_lines=4, same skip-names, same
tests-excluded semantics. quality-gate/tests/test_reuse_injector.py imports
both sides and pins them; edit either one only in lockstep.

CLI fallback (vendor-neutral, works without any hook runner):
    python reuse_injector.py --scan <path.py> [...]
prints the same match lines the hook would inject for those files' contents.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

MIN_LINES = 4               # same as qg checks_duplicates default
MAX_SUGGESTIONS = 5
MAX_CONTEXT_CHARS = 1200
MAX_INDEX_FILES = 3000      # beyond this, stay silent rather than slow Writes
MAX_FILE_BYTES = 1_000_000  # skip huge files
CACHE_REL = ".harness/cache/reuse-index.json"

# Skip lists — MUST stay in lockstep with quality-gate/qg/checks_duplicates.py
# (base set + _ALEMBIC_SKIP_NAMES + _ENUM_SKIP_NAMES). Pinned by the parity test.
_SKIP_NAMES = {
    "constructor", "render", "main", "init", "setup",
    "__init__", "__repr__", "__str__",
    "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
    "upgrade", "downgrade",                                   # alembic
    "values", "label", "labels", "choices", "from_value", "from_label",  # enums
}

# Directories never worth indexing (vendored, generated, machinery).
_SKIP_DIRS = {
    ".git", ".harness", ".claude", "__pycache__", ".venv", "venv",
    "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache",
    ".ruff_cache",
}


def is_test_path(path_text: str) -> bool:
    """Tests-excluded semantics — parity with QualityGate._is_test_path for
    Python paths (test helpers are not reuse candidates for production code)."""
    rel = path_text.replace("\\", "/").lower()
    name = rel.rsplit("/", 1)[-1]
    return (
        "/tests/" in rel
        or "/test/" in rel
        or rel.startswith("tests/")
        or rel.startswith("test/")
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _node_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str, int] | None:
    """The name-independent (signature, name, line) of one function — or None
    when it is private, a known idiom (skip-names), or under MIN_LINES."""
    func_name = node.name
    if not func_name or func_name.startswith("_") or func_name in _SKIP_NAMES:
        return None
    start = int(getattr(node, "lineno", 1) or 1)
    end = int(getattr(node, "end_lineno", start) or start)
    if (end - start) + 1 < MIN_LINES:
        return None
    # Exact formula of qg/checks_duplicates.py: hash arguments + body, never
    # the name — a clone that was only renamed must still match.
    arg_dump = ast.dump(node.args, include_attributes=False)
    body_dump = "|".join(ast.dump(stmt, include_attributes=False) for stmt in node.body)
    return (f"python:{_hash_text(arg_dump + '||' + body_dump)}", func_name, start)


def collect_signatures(content: str) -> list[tuple[str, str, int]]:
    """(signature, name, line) for each public top-level function spanning at
    least MIN_LINES lines. Fragments that do not parse yield nothing."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:  # invalid/partial code → nothing to match
        print(f"reuse-injector: unparseable candidate skipped: {exc}", file=sys.stderr)
        return []
    out: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = _node_signature(node)
            if sig is not None:
                out.append(sig)
    return out


# ── Repo index (cached per file on mtime+size) ────────────────────────


def _list_py_files(root: Path) -> list[str] | None:
    """Relative posix paths of candidate .py files, or None when the repo is
    too large to index within a Write's latency budget (→ stay silent)."""
    files: list[str] | None = None
    try:
        proc = subprocess.run(["git", "ls-files", "--", "*.py"], cwd=str(root),
                              capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            stripped = (ln.strip() for ln in proc.stdout.splitlines())
            files = [ln for ln in stripped if ln.endswith(".py")]
    except Exception as exc:  # git missing/hung — fall through to the walk
        print(f"reuse-injector: git ls-files unavailable ({exc})", file=sys.stderr)
        files = None
    if files is None:  # not a git repo — bounded filesystem walk
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for fn in filenames:
                if fn.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), root)
                    files.append(rel.replace("\\", "/"))
            if len(files) > MAX_INDEX_FILES:
                return None
    unique = sorted(set(files))
    if len(unique) > MAX_INDEX_FILES:
        return None
    return unique


def _load_cache(cache_path: Path) -> dict:
    """Best-effort read; a corrupt/absent cache is simply an empty one."""
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        entries = data.get("files")
        return entries if isinstance(entries, dict) else {}
    except Exception as exc:  # corrupt cache is expected garbage — rebuild
        print(f"reuse-injector: cache ignored, rebuilding: {exc}", file=sys.stderr)
        return {}


def _save_cache(cache_path: Path, entries: dict) -> None:
    """Best-effort write — a read-only tree must not break the hook."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"version": 1, "files": entries}),
                              encoding="utf-8", newline="\n")
    except Exception as exc:  # breadcrumb only; fail-open
        print(f"reuse-injector: cache write skipped: {exc}", file=sys.stderr)


def _file_funcs(path: Path, st: os.stat_result, entry: object) -> list | None:
    """This file's [signature, name, line] rows — from cache when (mtime, size)
    both match, else re-parsed. None means the file could not be read."""
    if (isinstance(entry, dict) and entry.get("mtime") == st.st_mtime
            and entry.get("size") == st.st_size
            and isinstance(entry.get("funcs"), list)):
        return entry["funcs"]
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"reuse-injector: unreadable file skipped: {exc}", file=sys.stderr)
        return None
    return [list(t) for t in collect_signatures(content)]


def _index_funcs(funcs: list, rel: str, by_sig: dict, by_name: dict) -> None:
    for item in funcs:
        try:
            sig, name, line = str(item[0]), str(item[1]), int(item[2])
        except (IndexError, TypeError, ValueError) as exc:  # malformed cache row
            print(f"reuse-injector: malformed index row skipped: {exc}", file=sys.stderr)
            continue
        by_sig.setdefault(sig, []).append((rel, line, name))
        by_name.setdefault(name, []).append((rel, line))


def _build_index(root: Path, exclude_rel: str | None) -> tuple[dict, dict] | None:
    """by_signature and by_name maps over the repo's production Python,
    excluding the file being written and all test paths."""
    files = _list_py_files(root)
    if files is None:
        return None
    cache_path = root / CACHE_REL
    cached = _load_cache(cache_path)
    fresh: dict = {}
    by_sig: dict[str, list[tuple[str, int, str]]] = {}
    by_name: dict[str, list[tuple[str, int]]] = {}
    for rel in files:
        if rel == exclude_rel or is_test_path(rel):
            continue
        path = root / rel
        try:
            st = path.stat()
        except OSError as exc:
            print(f"reuse-injector: stat failed, file skipped: {exc}", file=sys.stderr)
            continue
        if st.st_size > MAX_FILE_BYTES:
            continue
        funcs = _file_funcs(path, st, cached.get(rel))
        if funcs is None:
            continue
        fresh[rel] = {"mtime": st.st_mtime, "size": st.st_size, "funcs": funcs}
        _index_funcs(funcs, rel, by_sig, by_name)
    _save_cache(cache_path, fresh)
    return by_sig, by_name


def _relative_to_root(file_path: str, root: Path) -> str | None:
    try:
        fp = Path(file_path)
        if not fp.is_absolute():
            fp = root / fp
        return fp.resolve().relative_to(root.resolve()).as_posix()
    except Exception as exc:  # outside the repo — nothing to exclude
        print(f"reuse-injector: target not under root: {exc}", file=sys.stderr)
        return None


# ── Matching ──────────────────────────────────────────────────────────


def suggest_reuse(root: Path, file_path: str, candidate: str) -> list[str]:
    """The deterministic suggestion lines for writing `candidate` to
    `file_path` under `root` — [] means stay silent."""
    cand = collect_signatures(candidate)
    if not cand:
        return []
    index = _build_index(root, _relative_to_root(file_path, root))
    if index is None:
        return []
    by_sig, by_name = index
    matches: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for sig, _name, _line in cand:                       # TIER-1: exact body hash
        for rel, line, existing in by_sig.get(sig, []):
            if (rel, line) not in seen:
                seen.add((rel, line))
                matches.append((rel, line, f"identical implementation: {existing} at "
                                           f"{rel}:{line} — reuse instead of regenerating"))
    for _sig, name, _line in cand:                       # TIER-2: same public name
        for rel, line in by_name.get(name, []):
            if (rel, line) not in seen:
                seen.add((rel, line))
                matches.append((rel, line, f"same-name symbol exists: {name} at {rel}:{line}"))
    matches.sort(key=lambda m: (m[0], m[1], m[2]))       # stable (path, line)
    return [m[2] for m in matches[:MAX_SUGGESTIONS]]


def _build_context(lines: list[str]) -> str:
    header = "Reuse check — similar existing symbols in this repo:"
    kept = list(lines)
    text = "\n".join([header] + [f"- {ln}" for ln in kept])
    while len(text) > MAX_CONTEXT_CHARS and len(kept) > 1:
        kept.pop()
        text = "\n".join([header] + [f"- {ln}" for ln in kept])
    return text[:MAX_CONTEXT_CHARS]


def _emit(text: str) -> None:
    """utf-8 bytes straight to the fd — never trust the console codepage."""
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


# ── Entry points ──────────────────────────────────────────────────────


def _candidate_from_input(tool_name: str, tool_input: dict) -> tuple[str, str] | None:
    """(file_path, candidate_text) when the tool input targets production
    Python with non-empty new code; None otherwise."""
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return None
    if is_test_path(file_path):
        return None
    candidate = tool_input.get("content" if tool_name == "Write" else "new_string")
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    return file_path, candidate


def _hook_request(payload: object) -> tuple[Path, str, str] | None:
    """(root, file_path, candidate) when this event warrants a reuse check;
    None for everything else (non-Write/Edit tools, non-Python, tests,
    malformed payloads — defense in depth behind the settings matcher)."""
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if tool_name not in ("Write", "Edit") or not isinstance(tool_input, dict):
        return None
    target = _candidate_from_input(tool_name, tool_input)
    if target is None:
        return None
    root = Path(payload.get("cwd") or os.getcwd())
    if not root.is_dir():
        return None
    return root, target[0], target[1]


def _run_hook() -> int:
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    request = _hook_request(payload)
    if request is None:
        return 0
    root, file_path, candidate = request
    lines = suggest_reuse(root, file_path, candidate)
    if not lines:
        return 0
    _emit(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": _build_context(lines),
    }}, sort_keys=True))
    return 0


def _run_cli(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="reuse_injector",
        description="Print the reuse suggestions the PreToolUse hook would "
                    "inject for each file's content (CLI fallback).")
    parser.add_argument("--scan", nargs="+", required=True, metavar="PATH",
                        help="Python files to check against the repo index")
    parser.add_argument("--root", default=".",
                        help="repo root to index (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    for path_arg in args.scan:
        target = Path(path_arg)
        if not target.is_absolute():
            target = root / target
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"reuse-injector: cannot read {path_arg}: {exc}", file=sys.stderr)
            continue
        for line in suggest_reuse(root, str(target), content):
            _emit(line + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Fail-open is absolute: whatever happens — bad JSON, bad args, broken
    cache, unreadable tree — this returns 0. NEVER 2 (2 = block the tool)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run_cli(argv) if argv else _run_hook()
    except SystemExit:  # argparse exits 2 on bad usage — it already printed why
        return 0
    except Exception as exc:  # breadcrumb only; never a nonzero exit
        print(f"reuse-injector: fail-open: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
