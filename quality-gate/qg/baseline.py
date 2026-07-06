"""Per-file PRS baseline & ratchet — Clean-as-You-Code for brownfield repos.

A baseline is a committed, provenance-stamped snapshot of every scanned
file's PRS counts ({prs, errors, warnings, vetoed}), keyed by
forward-slash-normalized relpaths so a baseline written on Windows
matches keys in POSIX CI. The ratchet then enforces non-regression:

  * A scanned file whose key is in the baseline passes iff
    errors <= baselined errors AND warnings <= baselined warnings AND
    PRS >= baselined PRS. Non-regressed below-floor files raise NO
    'prs_score' error, and their pre-existing error findings are
    excluded from the engine's pass/fail count (still fully reported) —
    legacy debt is tolerated, not endorsed.
  * Any regression raises an ERROR with rule 'baseline_ratchet' that
    names the regressed metric (e.g. "errors 2 > baselined 1").
  * A vetoed file always fails — a baseline never masks a security veto.
  * A file absent from the baseline (new code) must meet the existing
    PRS floor unchanged.
  * Files in the baseline but not scanned are ignored (diff-scoped CI);
    pruning happens only on an explicit `--mode baseline` re-run.

Anti-regeneration is 3-layered: (a) mechanical — write_baseline refuses
under CI env (CI/GITHUB_ACTIONS) without an explicit allow flag;
(b) provenance — generated_at/commit/generated_by stamp every write and
check/audit modes never write; (c) process — the baseline path sits on
the protected surface (CODEOWNERS), so regenerations require owner review.

Identity is count-based in v1 (errors/warnings/PRS per file), so enabling
new rule packs can shift counts with no code change; a findings-hash
identity is the v2 upgrade path.

Stdlib only. Fail-closed: a corrupt baseline is 'baseline_unreadable',
distinct from 'baseline_missing' — never silently ratchet-free.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

BASELINE_VERSION = 1
GENERATED_BY = "quality-gate baseline"
DEFAULT_BASELINE_FILENAME = ".quality-gate.baseline.json"

_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS")
_FALSY_ENV = {"", "0", "false", "no", "off"}


def normalize_key(rel: str) -> str:
    """Normalize a relpath key to forward slashes (Windows <-> POSIX)."""
    return str(rel).replace("\\", "/")


# ── Build & write (provenance-stamped, CI-refusing) ───────────────────

def _git_commit(git_root) -> str:
    """Current git HEAD SHA for the provenance stamp, or 'unknown'."""
    if not git_root:
        return "unknown"
    try:
        proc = subprocess.run(
            ["git", "-c", f"safe.directory={git_root}", "-C", str(git_root),
             "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and sha else "unknown"


def build_baseline(
    file_prs: Mapping[str, Mapping[str, Any]],
    *,
    root,
    min_score: int,
    git_root=None,
) -> dict:
    """Snapshot per-file PRS counts into a provenance-stamped baseline dict.

    ``min_score`` is informational only: floor checks always use the
    current (review-gated) config, so a stale baseline cannot silently
    lower the floor.
    """
    files: dict[str, dict[str, Any]] = {}
    for rel, meta in (file_prs or {}).items():
        files[normalize_key(rel)] = {
            "prs": float(meta.get("score", 0.0)),
            "errors": int(meta.get("errors", 0)),
            "warnings": int(meta.get("warnings", 0)),
            "vetoed": bool(meta.get("vetoed", False)),
        }
    return {
        "version": BASELINE_VERSION,
        "generated_by": GENERATED_BY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git_commit(git_root or root),
        "min_score": int(min_score),
        "files": files,
    }


def ci_env_active(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Name of the first truthy CI env var, or None outside CI."""
    env = os.environ if env is None else env
    for var in _CI_ENV_VARS:
        if str(env.get(var, "")).strip().lower() not in _FALSY_ENV:
            return var
    return None


def ci_refusal(*, allow_ci: bool = False,
               env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Refusal message when a baseline write is not allowed here, else None."""
    var = ci_env_active(env)
    if var and not allow_ci:
        return (
            f"Refusing to write baseline: {var} environment detected. "
            "Baselines are generated locally and committed as a reviewable "
            "diff, never regenerated in CI. Pass --allow-ci-baseline to "
            "override explicitly."
        )
    return None


def write_baseline(path, data: dict, *, allow_ci: bool = False,
                   env: Optional[Mapping[str, str]] = None) -> Tuple[bool, str]:
    """Write a baseline (keys '/', sorted, indent=2, trailing newline).

    Hard-refuses under CI env unless ``allow_ci`` — the mechanical layer
    of the anti-regeneration guarantee. Returns (ok, message).
    """
    refusal = ci_refusal(allow_ci=allow_ci, env=env)
    if refusal:
        return False, refusal
    payload = dict(data)
    payload["files"] = {
        normalize_key(k): v for k, v in (data.get("files") or {}).items()
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    except OSError as exc:
        return False, f"Failed to write baseline {path}: {exc}"
    return True, (
        f"Baseline written: {path} ({len(payload['files'])} files, "
        f"commit {payload.get('commit', 'unknown')})"
    )


# ── Load (fail-closed: corrupt is distinct from missing) ─────────────

def load_baseline(path) -> Tuple[Optional[dict], str]:
    """Load a baseline. Returns (data|None, status in {ok, missing, unreadable})."""
    p = Path(path)
    if not p.exists():
        return None, "missing"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "unreadable"
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return None, "unreadable"
    return data, "ok"


def resolve_baseline_path(flag_value, config, root_dir) -> Tuple[Path, bool]:
    """Resolve the baseline path. Returns (path, explicit).

    Priority: --baseline flag (explicit) > config key baseline.path >
    DEFAULT_BASELINE_FILENAME at the project root. Only an explicit flag
    makes a *missing* baseline fail closed; a config-derived path stays
    dormant until the file exists (corrupt always fails closed).
    """
    if flag_value:
        return Path(flag_value), True
    bcfg = config.get("baseline") if isinstance(config, dict) else None
    rel = bcfg.get("path") if isinstance(bcfg, dict) else None
    p = Path(rel or DEFAULT_BASELINE_FILENAME)
    return (p if p.is_absolute() else Path(root_dir) / p), False


def init_state(flag_value, config, root_dir) -> Tuple[str, bool, Optional[dict], str]:
    """Engine helper: resolve + load in one call.

    Returns (path, explicit, data|None, status).
    """
    path, explicit = resolve_baseline_path(flag_value, config, root_dir)
    data, status = load_baseline(path)
    return str(path), explicit, data, status


def load_failure_issue(path, status: str, *, explicit: bool) -> Optional[dict]:
    """Synthetic ERROR when a requested baseline cannot be used (fail closed)."""
    spath = str(path)
    if status == "unreadable":
        return {
            "file": spath, "line": 0, "rule": "baseline_unreadable",
            "severity": "error",
            "message": (
                f"Baseline at {spath} exists but could not be parsed — failing "
                "closed. A gate whose baseline is unreadable must not silently "
                "run ratchet-free."
            ),
            "suggestion": (
                "Fix or delete the file, or regenerate it locally via "
                "--mode baseline and commit the reviewable diff."
            ),
        }
    if status == "missing" and explicit:
        return {
            "file": spath, "line": 0, "rule": "baseline_missing",
            "severity": "error",
            "message": (
                f"Baseline explicitly requested but not found at {spath} — "
                "failing closed (never silently ratchet-free)."
            ),
            "suggestion": (
                "Generate it locally via --mode baseline and commit it, or "
                "drop the --baseline flag."
            ),
        }
    return None


# ── Compare & ratchet (per-file, order-independent) ───────────────────

def _entry_regressions(meta: Mapping[str, Any], entry: Mapping[str, Any]) -> list:
    """Regressed-metric descriptions vs a baseline entry (empty = tolerated).

    Missing/malformed entry fields coerce to the strictest value (0 counts,
    PRS 100) so a hand-edited baseline degrades fail-closed, not open.
    """
    def _num(value, default, cast):
        try:
            return cast(value)
        except (TypeError, ValueError):
            return default

    errors = int(meta.get("errors", 0))
    warnings = int(meta.get("warnings", 0))
    score = float(meta.get("score", 0.0))
    base_errors = _num(entry.get("errors"), 0, int)
    base_warnings = _num(entry.get("warnings"), 0, int)
    base_prs = _num(entry.get("prs"), 100.0, float)

    reasons = []
    if errors > base_errors:
        reasons.append(f"errors {errors} > baselined {base_errors}")
    if warnings > base_warnings:
        reasons.append(f"warnings {warnings} > baselined {base_warnings}")
    if score < base_prs:
        reasons.append(f"PRS {score:.1f} < baselined {base_prs:.1f}")
    return reasons


def _veto_verdict(in_baseline: bool) -> dict:
    return {
        "in_baseline": in_baseline, "failed": True, "rule": "prs_score",
        "message": ("PRS VETOED (critical/security finding) — a baseline "
                    "never masks a security veto."),
        "reasons": ["vetoed"],
    }


def _ratchet_verdict(meta: Mapping[str, Any], entry: Mapping[str, Any]) -> dict:
    reasons = _entry_regressions(meta, entry)
    return {
        "in_baseline": True,
        "failed": bool(reasons),
        "rule": "baseline_ratchet" if reasons else None,
        "message": ("Baseline ratchet: " + "; ".join(reasons) + ".") if reasons else None,
        "reasons": reasons,
    }


def _floor_verdict(meta: Mapping[str, Any], min_score: float) -> dict:
    score = float(meta.get("score", 0.0))
    below = score < float(min_score)
    return {
        "in_baseline": False,
        "failed": below,
        "rule": "prs_score" if below else None,
        "message": (f"PRS {score:.1f}/100 below minimum {int(min_score)} "
                    "(new file — not in baseline).") if below else None,
        "reasons": [],
    }


def compare_to_baseline(
    file_prs: Mapping[str, Mapping[str, Any]],
    baseline: Optional[Mapping[str, Any]],
    min_score: float,
) -> dict:
    """Per-file verdicts keyed by normalized relpath (order-independent).

    Pure dict-key lookup on normalized keys: scan order can never
    fabricate or hide a regression. Verdict shape:
    {in_baseline, failed, rule, message, reasons}.
    """
    base_files = (baseline or {}).get("files") or {}
    base_norm = {normalize_key(k): v for k, v in base_files.items()
                 if isinstance(v, Mapping)}
    verdicts: dict[str, dict[str, Any]] = {}
    for rel, meta in (file_prs or {}).items():
        key = normalize_key(rel)
        entry = base_norm.get(key)
        if bool(meta.get("vetoed")):
            verdicts[key] = _veto_verdict(entry is not None)
        elif entry is not None:
            verdicts[key] = _ratchet_verdict(meta, entry)
        else:
            verdicts[key] = _floor_verdict(meta, min_score)
    return verdicts


_SUGGESTIONS = {
    "baseline_ratchet": (
        "New code must not regress below the committed baseline. Fix the "
        "new findings, or re-baseline deliberately via --mode baseline "
        "(the diff is review-gated)."
    ),
    "prs_score": (
        "Fix critical/security findings first, or fix errors/warnings in "
        "this file; split large functions/files; improve error handling."
    ),
}


def apply_ratchet(
    file_prs: Mapping[str, Mapping[str, Any]],
    baseline: Optional[Mapping[str, Any]],
    min_score: float,
) -> dict:
    """Ratchet outcome for the engine: issues to raise + stats + fail count.

    Issue dicts keep the engine's original relpath in 'file' so the call
    site can anchor them; stats carry baseline_files_matched /
    baseline_ratchet_failed / baseline_new_files. 'tolerated' lists the
    normalized keys of baselined, non-regressed, non-vetoed files: their
    pre-existing findings are known debt the caller must not fail on
    (that toleration IS the brownfield unlock — without it a baselined
    repo with any error-severity debt could never go green).
    """
    verdicts = compare_to_baseline(file_prs, baseline, min_score)
    pairs = [(rel, verdicts[normalize_key(rel)]) for rel in (file_prs or {})]
    issues = [
        {
            "file": rel, "line": 1, "rule": verdict["rule"],
            "severity": "error", "message": verdict["message"],
            "suggestion": _SUGGESTIONS.get(verdict["rule"], ""),
        }
        for rel, verdict in pairs if verdict["failed"]
    ]
    return {
        "issues": issues,
        "failed": len(issues),
        "tolerated": sorted(
            normalize_key(rel) for rel, v in pairs
            if v["in_baseline"] and not v["failed"]
        ),
        "stats": {
            "baseline_files_matched": sum(1 for _, v in pairs if v["in_baseline"]),
            "baseline_ratchet_failed": sum(
                1 for _, v in pairs if v["in_baseline"] and v["failed"]),
            "baseline_new_files": sum(1 for _, v in pairs if not v["in_baseline"]),
        },
    }


def report_block(path, status: str, data: Optional[Mapping[str, Any]],
                 stats: Mapping[str, Any]) -> dict:
    """Additive 'baseline' block for the JSON report (safe for consumers)."""
    return {
        "path": normalize_key(str(path)),
        "status": status,
        "commit": (data or {}).get("commit"),
        "matched": int(stats.get("baseline_files_matched", 0) or 0),
        "regressed": int(stats.get("baseline_ratchet_failed", 0) or 0),
    }
