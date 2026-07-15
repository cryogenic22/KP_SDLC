"""Commit-pinned, SANITIZED baseline manifest for the CTX dogfood-value eval.

This freezes Git + ledger + CTX-runtime state across the dogfood repos so a later
CTX-VALUE measurement is reproducible. It is the measurement substrate, NOT a
value claim: it proves capture health and pins the environment, nothing more.

Four properties this module owns (each has a test that goes red if it is removed):

* Snapshot consistency (no torn read). The ledger churns — it is written by live
  session hooks. So we read the ledger bytes, compute the aggregates from a FROZEN
  COPY of exactly those bytes (a temp ledger the canonical ``ctxpack session
  stats`` runs against), then re-read the live files and verify they are
  unchanged. A mid-capture change RETRIES, and after ``attempts`` failures the
  entry is marked ``torn`` and we FAIL CLOSED. We never hash the files and then
  separately invoke live ``session stats`` — those could observe different states.

* Runtime provenance (pin what actually ran). ``CTX_mod@<commit>`` is not enough:
  each hook/MCP server invokes Python independently and may resolve a different
  ctxpack via ``PYTHONPATH`` (Market Zero ships an extra ``ctxpack-code`` MCP
  server; Transmax does not). We record the resolved ctxpack module + source
  hash, the Python identity, the package version, and per-repo hook/MCP launch
  hashes + which servers set ``PYTHONPATH``.

* Split dirty state. A single ``dirty`` flag conflates code, ledger, and config.
  All four repos are "dirty" only because their ledgers churn, which says nothing
  about whether the CODE is reproducible. We split into code/ledger/config.

* Privacy by construction. The manifest is BORN sanitized: hashes, counts, opaque
  labels, commit shas, and MCP server names only — never raw transcript content,
  absolute paths, session UUIDs, usernames, env values, or raw commands. The tool
  REFUSES to emit if ``scan_forbidden`` matches; a test scans the artifact too.

CLI (repo paths come from an UNCOMMITTED config file, so the code carries none)::

    python -m eval_engine.ctx_baseline --repos-config repos.json --out manifest.json

``repos.json`` is a list of ``{"label": "repo-a", "path": "/abs/path"}``. Exit is
0 only on a schema-valid, no-torn capture; a torn capture or a schema/privacy
violation is a loud non-zero (fail closed).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import logging
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("ctx_baseline")

MANIFEST_TAG = "ctx-dogfood-baseline/manifest@1"
GENERATOR_TOOL = "eval_engine.ctx_baseline"
GENERATOR_VERSION = "1"
_DEFAULT_ATTEMPTS = 4

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "eval" / "ctx-dogfood-baseline.schema.json"

# The two named ledger files; every other session artifact (a *.ctx pack or a
# *gist*.md) is hashed under an OPAQUE id (its real filename embeds a UUID).
_EVENTS = "events.jsonl"
_CHECKPOINTS = "checkpoints.jsonl"
_SETTINGS_REL = (".claude", "settings.json")
_MCP_REL = (".mcp.json",)


# ── low-level: hashing / git / file read ─────────────────────────────

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _shatext(text: str) -> str:
    return _sha(text.encode("utf-8"))


def _read_if_file(path: Path) -> bytes | None:
    """The file's bytes, or None if it does not exist (single read call site)."""
    return path.read_bytes() if path.is_file() else None


def _git(root: str, *args: str) -> str:
    """Run git in ``root``; '' on any failure (git absent, not a repo)."""
    try:
        proc = subprocess.run(["git", "-C", root, *args], capture_output=True,
                              encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("git unavailable in %s: %s", root, exc)
        return ""
    return (proc.stdout or "").strip()


# ── ledger snapshot (torn-read safe) ─────────────────────────────────

def _session_artifact_paths(ctx_dir: Path) -> list[Path]:
    """Session-artifact files (packs + gists), sorted for a stable opaque id."""
    if not ctx_dir.is_dir():
        return []
    arts = [p for p in ctx_dir.iterdir()
            if p.is_file() and (p.suffix == ".ctx" or (p.suffix == ".md" and "gist" in p.name))]
    return sorted(arts, key=lambda p: p.name)


def _read_ledger_bytes(ctx_dir: Path) -> dict[str, bytes]:
    """Read every ledger file's bytes in one pass, keyed by a STABLE key: events /
    checkpoints keep their name; artifacts get an opaque ``artifact-N`` key."""
    pairs = [(name, ctx_dir / name) for name in (_EVENTS, _CHECKPOINTS)]
    pairs += [(f"artifact-{i}", p) for i, p in enumerate(_session_artifact_paths(ctx_dir), start=1)]
    return {key: data for key, data in ((k, _read_if_file(p)) for k, p in pairs) if data is not None}


def _hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {k: _sha(v) for k, v in sorted(files.items())}


def _default_stats_fn(frozen: dict[str, bytes]) -> dict:
    """Compute ``ctxpack session stats`` from a FROZEN copy of the ledger bytes:
    the exact hashed bytes are written into a throwaway ``.claude/ctx`` and the
    canonical CLI runs there, so aggregates cannot observe a different (live)
    ledger state than the one we hashed."""
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td) / ".claude" / "ctx"
        ctx.mkdir(parents=True)
        for key, data in frozen.items():
            name = key if key in (_EVENTS, _CHECKPOINTS) else f"{key}.ctx"
            (ctx / name).write_bytes(data)
        proc = subprocess.run(
            [sys.executable, "-P", "-m", "ctxpack.cli.main", "session", "stats"],
            cwd=td, capture_output=True, encoding="utf-8", errors="replace")
        try:
            return json.loads(proc.stdout)
        except (ValueError, TypeError) as exc:
            logger.warning("session stats returned no JSON: %s", exc)
            return {"_error": "session stats did not return JSON",
                    "_stderr": (proc.stderr or "")[:200]}


def _unchanged(ctx_dir: Path, before_h: dict[str, str]) -> bool:
    """True iff the live ledger still hashes to ``before_h`` (no mid-capture write)."""
    return _hashes(_read_ledger_bytes(ctx_dir)) == before_h


def _cap_result(torn: bool, attempts: int, before: dict[str, bytes],
                before_h: dict[str, str], stats: dict) -> dict:
    return {"torn": torn, "capture_attempts": attempts, "hashes": before_h,
            "byte_lengths": {k: len(v) for k, v in before.items()}, "stats": stats}


def capture_ledger(ctx_dir: Path, attempts: int = _DEFAULT_ATTEMPTS, *, stats_fn=_default_stats_fn) -> dict:
    """Torn-read-safe capture: hash bytes, derive stats from those SAME bytes,
    re-verify the live files, retry on mid-capture change, fail closed. ``torn``
    True means the ledger changed under us every attempt — the entry is untrusted."""
    before: dict[str, bytes] = {}
    before_h: dict[str, str] = {}
    stats: dict = {}
    for attempt in range(1, max(1, attempts) + 1):
        before = _read_ledger_bytes(ctx_dir)
        before_h = _hashes(before)
        stats = stats_fn(before)                 # derived from the frozen bytes
        if _unchanged(ctx_dir, before_h):
            return _cap_result(False, attempt, before, before_h, stats)
    return _cap_result(True, attempts, before, before_h, stats)


def _ledger_block(cap: dict) -> dict:
    """Shape the ledger section from a capture result — opaque artifact ids."""
    hashes, lengths = cap["hashes"], cap["byte_lengths"]

    def entry(key):
        return None if key not in hashes else {"sha256": hashes[key], "bytes": lengths.get(key)}

    arts = [{"id": k, "sha256": hashes[k], "bytes": lengths.get(k)}
            for k in sorted(hashes) if k.startswith("artifact-")]
    return {
        "torn": cap["torn"],
        "capture_attempts": cap["capture_attempts"],
        "events_jsonl": entry(_EVENTS),
        "checkpoints_jsonl": entry(_CHECKPOINTS),
        "session_artifacts": arts,
    }


# ── git split-dirty ──────────────────────────────────────────────────

def _classify(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith(".claude/ctx/"):
        return "ledger"
    if p in (".claude/settings.json", ".mcp.json"):
        return "config"
    return "code"


def _split_dirty(root: str) -> dict:
    """Split ``git status`` into code / ledger / config, and hash the non-ledger,
    non-config change manifest (path+status only — no file content)."""
    porcelain = _git(root, "status", "--porcelain", "--untracked-files=all")
    buckets: dict[str, list[str]] = {"code": [], "ledger": [], "config": []}
    for line in porcelain.splitlines():
        if line.strip():
            buckets[_classify(line[3:] if len(line) > 3 else line)].append(line)
    non_ledger = sorted(buckets["code"] + buckets["config"])
    return {
        "branch_sha256": _shatext(_git(root, "rev-parse", "--abbrev-ref", "HEAD")),
        "commit": _git(root, "rev-parse", "HEAD"),
        "code_worktree_dirty": bool(buckets["code"]),
        "ledger_dirty": bool(buckets["ledger"]),
        "config_dirty": bool(buckets["config"]),
        "non_ledger_diff_sha256": _shatext("\n".join(non_ledger)),
    }


# ── config provenance (hook + MCP) ───────────────────────────────────

def _commands_in_group(group: dict) -> list[str]:
    return [h.get("command") for h in (group.get("hooks") or []) if isinstance(h.get("command"), str)]


def _all_hook_groups(settings: dict) -> list[dict]:
    """Flatten every event's hook groups into one list (keeps the caller flat)."""
    groups: list[dict] = []
    for event_groups in (settings.get("hooks") or {}).values():
        groups.extend(event_groups or [])
    return groups


def _hook_command_hashes(settings_raw: bytes | None) -> list[str]:
    if settings_raw is None:
        return []
    try:
        settings = json.loads(settings_raw)
    except ValueError:
        logger.warning("settings.json not parseable JSON")
        return []
    cmds: list[str] = []
    for group in _all_hook_groups(settings):
        cmds.extend(_commands_in_group(group))
    return sorted({_shatext(c) for c in cmds})


def _uses_pythonpath(env_keys: set, argv: list[str]) -> bool:
    return ("PYTHONPATH" in env_keys) or any("PYTHONPATH" in arg for arg in argv)


def _mcp_provenance(mcp_raw: bytes | None) -> tuple[list[str], dict, dict]:
    servers: list[str] = []
    launch_sha: dict[str, str] = {}
    sets_pp: dict[str, bool] = {}
    if mcp_raw is None:
        return servers, launch_sha, sets_pp
    try:
        mcp = json.loads(mcp_raw).get("mcpServers") or {}
    except ValueError:
        logger.warning(".mcp.json not parseable JSON")
        return servers, launch_sha, sets_pp
    for name, spec in sorted(mcp.items()):
        argv = [spec.get("command", "")] + list(spec.get("args") or [])
        servers.append(name)
        launch_sha[name] = _shatext(" ".join(argv))
        sets_pp[name] = _uses_pythonpath(set(spec.get("env") or {}), argv)
    return servers, launch_sha, sets_pp


def _config_provenance(root: Path) -> dict:
    settings_raw = _read_if_file(root.joinpath(*_SETTINGS_REL))
    mcp_raw = _read_if_file(root.joinpath(*_MCP_REL))
    servers, launch_sha, sets_pp = _mcp_provenance(mcp_raw)
    return {
        "settings_sha256": _sha(settings_raw) if settings_raw is not None else None,
        "mcp_sha256": _sha(mcp_raw) if mcp_raw is not None else None,
        "hook_commands_sha256": _hook_command_hashes(settings_raw),
        "mcp_servers": servers,
        "mcp_launch_sha256": launch_sha,
        "mcp_sets_pythonpath": sets_pp,
    }


# ── ctxpack runtime provenance ───────────────────────────────────────

def _resolve_ctxpack() -> dict:
    """Resolve the ctxpack that COMPUTES the aggregates. Paths are hashed, never
    emitted raw."""
    try:
        spec = importlib.util.find_spec("ctxpack")
    except (ImportError, ValueError) as exc:
        logger.warning("ctxpack not importable: %s", exc)
        spec = None
    if spec is None or not spec.origin:
        return {"module_path_sha256": "unresolved", "source_sha256": "unresolved", "impl_commit": None}
    pkg_dir = Path(spec.origin).parent
    pkg_dir_str = str(pkg_dir)
    srcs = b"".join(_read_if_file(pkg_dir / rel) or b""
                    for rel in ("__init__.py", "agent/session_reader.py"))
    return {
        "module_path_sha256": _shatext(pkg_dir_str),
        "source_sha256": _sha(srcs) if srcs else "empty",
        "impl_commit": _git(pkg_dir_str, "rev-parse", "HEAD") or None,
    }


def _ctxpack_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError as exc:
        logger.warning("importlib.metadata unavailable: %s", exc)
        return "unknown"
    try:
        return version("ctxpack")
    except PackageNotFoundError:
        logger.warning("ctxpack version metadata absent")
        return "unknown"


def _ctx_runtime() -> dict:
    return {
        "python_version": sys.version.split()[0],
        "python_executable_sha256": _shatext(sys.executable or ""),
        "ctxpack": {**_resolve_ctxpack(), "version": _ctxpack_version()},
    }


# ── manifest assembly ────────────────────────────────────────────────

def build_repo_entry(label: str, path: str, attempts: int, *, stats_fn=_default_stats_fn) -> dict:
    root = Path(path)
    cap = capture_ledger(root / ".claude" / "ctx", attempts, stats_fn=stats_fn)
    return {
        "label": label,
        "git": _split_dirty(str(root)),
        "ledger": _ledger_block(cap),
        "config": _config_provenance(root),
        "stats_checkpoint_surface": cap["stats"],
    }


def build_manifest(repos, attempts: int = _DEFAULT_ATTEMPTS, *, now=None, stats_fn=_default_stats_fn) -> dict:
    """Assemble the full manifest. ``repos`` is a list of {label, path}. ``now`` is
    injectable so tests are deterministic."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "schema": MANIFEST_TAG,
        "captured_at_utc": stamp,
        "generator": {"tool": GENERATOR_TOOL, "version": GENERATOR_VERSION},
        "ctx_runtime": _ctx_runtime(),
        "repos": [build_repo_entry(r["label"], r["path"], attempts, stats_fn=stats_fn) for r in repos],
    }


# ── schema validation (zero-dep subset: type/required/properties/items/enum/const) ──

_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
          "number": (int, float), "boolean": bool, "null": type(None)}


def _type_ok(value, spec_type) -> bool:
    names = spec_type if isinstance(spec_type, list) else [spec_type]
    for name in names:
        py = _TYPES.get(name)
        if py is None:
            return True
        if name in ("number", "integer") and isinstance(value, bool):
            continue                          # bool is not a number/integer here
        if isinstance(value, py):
            return True
    return False


def _check_scalar(instance, schema, path: str, errors: list[str]) -> None:
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum")
    if "type" in schema and not _type_ok(instance, schema["type"]):
        errors.append(f"{path}: expected type {schema['type']}, got {type(instance).__name__}")


def _check_object(instance: dict, schema: dict, path: str, errors: list[str]) -> None:
    for req in schema.get("required", []):
        if req not in instance:
            errors.append(f"{path}: missing required key '{req}'")
    for key, sub in (schema.get("properties") or {}).items():
        if key in instance:
            _validate(instance[key], sub, f"{path}.{key}", errors)


def _validate(instance, schema, path: str, errors: list[str]) -> None:
    _check_scalar(instance, schema, path, errors)
    if isinstance(instance, dict):
        _check_object(instance, schema, path, errors)
    elif isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            _validate(item, schema["items"], f"{path}[{i}]", errors)


def load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_manifest(manifest: dict, schema: dict | None = None) -> list[str]:
    """Return a list of schema violations ('' if valid)."""
    errors: list[str] = []
    _validate(manifest, schema or load_schema(), "$", errors)
    return errors


# ── privacy scanner (enforced, not just tested) ──────────────────────
# Defense in depth over born-sanitized construction: a regex sweep for the
# concrete leak shapes. 64-hex sha256 and 40-hex commits have no hyphens, so the
# UUID pattern never matches them; hashes contain no ``:/`` or ``/Users/``.
_FORBIDDEN = [
    ("windows_abs_path", re.compile(r"[A-Za-z]:[\\/]")),
    ("unix_home_path", re.compile(r"/(?:Users|home)/")),
    ("session_uuid", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
]


def scan_forbidden(text: str) -> list[str]:
    """Return ``"<name>: <match>"`` for every forbidden pattern found ('' = clean)."""
    return [f"{name}: {m}" for name, rx in _FORBIDDEN for m in rx.findall(text)]


# ── CLI ──────────────────────────────────────────────────────────────

def _load_repos_config(cfg_path: str) -> list[dict]:
    data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(
            isinstance(r, dict) and "label" in r and "path" in r for r in data):
        raise ValueError("repos-config must be a list of {label, path} objects")
    return data


def _emit(payload: str, out: str | None) -> None:
    if out:
        Path(out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


def run(repos_config: str, out: str | None, attempts: int) -> int:
    """Build → schema-validate → privacy-scan → emit. Shared by the standalone
    ``python -m eval_engine.ctx_baseline`` entry and the ``ee ctx-baseline``
    subcommand. Fails closed: schema or privacy violation → 1, torn capture → 2."""
    try:
        repos = _load_repos_config(repos_config)
    except (ValueError, OSError) as exc:
        print(f"[ctx-baseline] bad --repos-config: {exc}", file=sys.stderr)
        return 1

    manifest = build_manifest(repos, attempts)
    schema_errors = validate_manifest(manifest)
    if schema_errors:
        print("[ctx-baseline] manifest FAILED schema validation (fail closed):", file=sys.stderr)
        for err in schema_errors[:20]:
            print(f"[ctx-baseline]   {err}", file=sys.stderr)
        return 1

    payload = json.dumps(manifest, indent=2, sort_keys=True)
    leaks = scan_forbidden(payload)
    if leaks:
        print("[ctx-baseline] REFUSING to emit — privacy scan found leaks (fail closed):", file=sys.stderr)
        for leak in leaks[:20]:
            print(f"[ctx-baseline]   {leak}", file=sys.stderr)
        return 1

    _emit(payload, out)
    torn = [r["label"] for r in manifest["repos"] if r["ledger"]["torn"]]
    if torn:
        print(f"[ctx-baseline] TORN capture for {torn} — ledger changed mid-read "
              "(fail closed); re-run when the repos are idle.", file=sys.stderr)
        return 2
    print(f"[ctx-baseline] ok: {len(manifest['repos'])} repos, no torn reads", file=sys.stderr)
    return 0


def build_arg_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the baseline args on ``parser`` (reused by ``ee ctx-baseline``)."""
    parser.add_argument("--repos-config", required=True,
                        help="JSON list of {label, path}; kept OUT of git (carries abs paths).")
    parser.add_argument("--out", default=None, help="write manifest JSON here (default: stdout)")
    parser.add_argument("--attempts", type=int, default=_DEFAULT_ATTEMPTS,
                        help="torn-read retry budget before failing closed")
    return parser


def main(argv=None) -> int:
    ap = build_arg_parser(argparse.ArgumentParser(
        prog="ctx-baseline", description="Freeze a sanitized CTX dogfood baseline manifest."))
    args = ap.parse_args(argv)
    return run(args.repos_config, args.out, args.attempts)


if __name__ == "__main__":
    raise SystemExit(main())
