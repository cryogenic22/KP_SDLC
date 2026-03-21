"""CK-ARCH-DRIFT — Architectural Drift Scoring.

Maintains a baseline snapshot of architectural metrics and measures
drift from it over time.  Produces a numeric drift score and emits
findings when drift exceeds configured thresholds.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from cathedral_keeper.models import Evidence, Finding, normalize_path
from cathedral_keeper.python_graph import (
    PyGraph,
    build_import_graph,
    build_module_index,
    strongly_connected_components,
)
from cathedral_keeper.python_roots import resolve_python_roots
from cathedral_keeper.policies.dead_modules import check_dead_modules
from cathedral_keeper.policies.layer_direction import check_layer_direction
from cathedral_keeper.policies.boundaries import check_boundaries


# ── public API ──────────────────────────────────────────────────────

def compute_metrics(
    *,
    root: Path,
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
    policies_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute the full set of architectural metrics for the current state."""
    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=files, module_index=mod_index)

    # Cycles
    sccs = strongly_connected_components(graph)
    cycle_files: List[str] = []
    for scc in sccs:
        cycle_files.extend(scc)
    cycle_files = sorted(set(cycle_files))

    # Fan-in / fan-out
    fan_in: Dict[str, int] = {}
    fan_out: Dict[str, int] = {}
    for e in graph.edges:
        fan_out[e.src_file] = fan_out.get(e.src_file, 0) + 1
        fan_in[e.dst_file] = fan_in.get(e.dst_file, 0) + 1

    all_nodes = set(fan_in.keys()) | set(fan_out.keys())
    max_fan_in = max(fan_in.values()) if fan_in else 0
    max_fan_out = max(fan_out.values()) if fan_out else 0
    avg_fan_out = round(sum(fan_out.values()) / max(len(all_nodes), 1), 2)

    # Boundary violations count
    boundary_violations = 0
    if _enabled(policies_cfg, "CK-PY-BOUNDARIES"):
        boundary_violations = len(
            check_boundaries(
                root=root,
                cfg=policies_cfg.get("CK-PY-BOUNDARIES") or {},
                files=files,
                python_roots=python_roots,
            )
        )

    # Layer violations count
    layer_violations = 0
    if _enabled(policies_cfg, "CK-ARCH-LAYER-DIRECTION"):
        layer_violations = len(
            check_layer_direction(
                root=root,
                cfg=policies_cfg.get("CK-ARCH-LAYER-DIRECTION") or {},
                files=files,
                python_roots=python_roots,
            )
        )

    # Dead modules count
    dead_modules = 0
    if _enabled(policies_cfg, "CK-ARCH-DEAD-MODULES"):
        dead_modules = len(
            check_dead_modules(
                root=root,
                cfg=policies_cfg.get("CK-ARCH-DEAD-MODULES") or {},
                files=files,
                python_roots=python_roots,
            )
        )

    return {
        "total_modules": len(files),
        "total_import_edges": len(graph.edges),
        "cycle_count": len(sccs),
        "cycle_files": cycle_files,
        "boundary_violations": boundary_violations,
        "layer_violations": layer_violations,
        "dead_modules": dead_modules,
        "max_fan_in": max_fan_in,
        "max_fan_out": max_fan_out,
        "avg_fan_out": avg_fan_out,
    }


def save_baseline(
    *,
    root: Path,
    metrics: Dict[str, Any],
    baseline_path: Optional[Path] = None,
) -> Path:
    """Persist the baseline snapshot to disk."""
    path = baseline_path or (root / ".quality-reports" / "cathedral-keeper" / "baseline.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    commit = _current_commit(root)
    snapshot = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit or "unknown",
        "metrics": metrics,
    }
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return path


def load_baseline(path: Path) -> Optional[Dict[str, Any]]:
    """Load a previously saved baseline, or None if it doesn't exist."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_drift(
    *,
    root: Path,
    cfg: Dict[str, Any],
    files: List[Path],
    python_roots: List[Tuple[str, Path]],
    policies_cfg: Dict[str, Any],
) -> List[Finding]:
    """Compare current metrics to baseline and emit drift findings."""
    inner_cfg = cfg.get("config") or cfg

    baseline_rel = str(inner_cfg.get("baseline_path", ".quality-reports/cathedral-keeper/baseline.json"))
    baseline_path = root / baseline_rel
    baseline = load_baseline(baseline_path)

    if baseline is None:
        return [
            Finding(
                policy_id="CK-ARCH-DRIFT",
                title="No baseline snapshot found",
                severity="info",
                confidence="high",
                why_it_matters=(
                    "Drift scoring requires a baseline.  Run `ck baseline` to create one. "
                    "Without a baseline, CK cannot track architectural change over time."
                ),
                evidence=[
                    Evidence(
                        file=str(baseline_rel),
                        line=0,
                        snippet="(file not found)",
                        note=f"Expected baseline at: {baseline_path}",
                    )
                ],
                fix_options=["Run `ck baseline --root .` to create the initial baseline snapshot."],
                verification=[f"test -f {baseline_rel}"],
                metadata={"baseline_path": str(baseline_rel)},
            )
        ]

    base_metrics = baseline.get("metrics") or {}
    current = compute_metrics(
        root=root, files=files, python_roots=python_roots, policies_cfg=policies_cfg,
    )

    score, breakdown = _calculate_drift(base_metrics, current)

    warn_threshold = int(inner_cfg.get("warn_threshold", 10))
    fail_threshold = int(inner_cfg.get("fail_threshold", 25))

    if score == 0:
        return []

    if score >= fail_threshold:
        severity = "high"
    elif score >= warn_threshold:
        severity = "medium"
    else:
        severity = "low"

    comparison_lines = _build_comparison_table(base_metrics, current, breakdown)

    return [
        Finding(
            policy_id="CK-ARCH-DRIFT",
            title=f"Architectural drift score: {score}",
            severity=severity,
            confidence="high",
            why_it_matters=(
                "Architecture governance is only effective when it tracks change over time. "
                f"The current drift score of {score} indicates cumulative architectural "
                f"degradation since baseline (commit {baseline.get('commit', '?')[:8]})."
            ),
            evidence=[
                Evidence(
                    file=str(baseline_rel),
                    line=0,
                    snippet="\n".join(comparison_lines),
                    note=f"Score: {score} (warn={warn_threshold}, fail={fail_threshold})",
                )
            ],
            fix_options=[
                "Address the degradations listed in the breakdown to lower the score.",
                "If changes are intentional, run `ck baseline` to reset the baseline.",
            ],
            verification=["ck analyze --root ."],
            metadata={
                "drift_score": score,
                "breakdown": breakdown,
                "baseline_commit": baseline.get("commit", "unknown"),
                "current_metrics": current,
                "baseline_metrics": base_metrics,
            },
        )
    ]


# ── internals ──────────────────────────────────────────────────────

def _enabled(policies: Dict[str, Any], pid: str) -> bool:
    p = policies.get(pid) or {}
    return bool(p.get("enabled", False))


def _current_commit(root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _calculate_drift(
    base: Dict[str, Any], current: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """Return (total_score, breakdown_dict)."""
    breakdown: Dict[str, Any] = {}
    total = 0

    # New cycles: 10 pts each
    new_cycles = max(0, int(current.get("cycle_count", 0)) - int(base.get("cycle_count", 0)))
    if new_cycles > 0:
        pts = new_cycles * 10
        breakdown["new_cycles"] = {"delta": new_cycles, "weight": 10, "points": pts}
        total += pts

    # New boundary violations: 5 pts each
    new_bv = max(0, int(current.get("boundary_violations", 0)) - int(base.get("boundary_violations", 0)))
    if new_bv > 0:
        pts = new_bv * 5
        breakdown["new_boundary_violations"] = {"delta": new_bv, "weight": 5, "points": pts}
        total += pts

    # New layer violations: 5 pts each
    new_lv = max(0, int(current.get("layer_violations", 0)) - int(base.get("layer_violations", 0)))
    if new_lv > 0:
        pts = new_lv * 5
        breakdown["new_layer_violations"] = {"delta": new_lv, "weight": 5, "points": pts}
        total += pts

    # Module count growth: 1 pt per 5% growth
    base_mod = max(1, int(base.get("total_modules", 1)))
    cur_mod = int(current.get("total_modules", 0))
    growth_pct = ((cur_mod - base_mod) / base_mod) * 100
    if growth_pct > 0:
        pts = int(growth_pct / 5)
        if pts > 0:
            breakdown["module_growth"] = {"delta_pct": round(growth_pct, 1), "weight": "1 per 5%", "points": pts}
            total += pts

    # Edge density increase: 2 pts per 0.5 increase in avg fan-out
    base_afo = float(base.get("avg_fan_out", 0))
    cur_afo = float(current.get("avg_fan_out", 0))
    afo_delta = cur_afo - base_afo
    if afo_delta > 0:
        pts = int(afo_delta / 0.5) * 2
        if pts > 0:
            breakdown["edge_density"] = {"delta": round(afo_delta, 2), "weight": "2 per 0.5", "points": pts}
            total += pts

    # New dead modules: 1 pt each
    new_dm = max(0, int(current.get("dead_modules", 0)) - int(base.get("dead_modules", 0)))
    if new_dm > 0:
        pts = new_dm * 1
        breakdown["new_dead_modules"] = {"delta": new_dm, "weight": 1, "points": pts}
        total += pts

    return total, breakdown


def _build_comparison_table(
    base: Dict[str, Any], current: Dict[str, Any], breakdown: Dict[str, Any],
) -> List[str]:
    """Build a human-readable comparison for the evidence snippet."""
    lines = ["Metric                  | Baseline | Current | Delta"]
    lines.append("-" * 56)

    metrics = [
        ("total_modules", "Modules"),
        ("total_import_edges", "Import edges"),
        ("cycle_count", "Cycles"),
        ("boundary_violations", "Boundary violations"),
        ("layer_violations", "Layer violations"),
        ("dead_modules", "Dead modules"),
        ("max_fan_in", "Max fan-in"),
        ("max_fan_out", "Max fan-out"),
        ("avg_fan_out", "Avg fan-out"),
    ]
    for key, label in metrics:
        b = base.get(key, 0)
        c = current.get(key, 0)
        delta = _fmt_delta(b, c)
        lines.append(f"{label:<24}| {str(b):>8} | {str(c):>7} | {delta}")

    if breakdown:
        lines.append("")
        lines.append("Score breakdown:")
        for k, v in breakdown.items():
            lines.append(f"  {k}: +{v['points']} pts")

    return lines


def _fmt_delta(base: Any, current: Any) -> str:
    try:
        diff = float(current) - float(base)
        if diff == 0:
            return "  —"
        sign = "+" if diff > 0 else ""
        if isinstance(base, int) and isinstance(current, int):
            return f"{sign}{int(diff)}"
        return f"{sign}{diff:.2f}"
    except (ValueError, TypeError):
        return "  ?"
