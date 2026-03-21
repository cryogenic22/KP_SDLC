from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

from cathedral_keeper.blast_radius import BlastRadius, compute_blast_radius, identify_high_fan_in
from cathedral_keeper.coherence import check_coherence
from cathedral_keeper.config import CKConfig, load_config
from cathedral_keeper.git_utils import find_git_root, git_changed_files
from cathedral_keeper.integrations.registry import run_integration
from cathedral_keeper.integrations.types import IntegrationContext, parse_enabled_integrations
from cathedral_keeper.models import Evidence, Finding, normalize_path, severity_rank
from cathedral_keeper.path_glob import filter_paths
from cathedral_keeper.policies.boundaries import check_boundaries
from cathedral_keeper.policies.config_sprawl import check_config_sprawl
from cathedral_keeper.policies.cycles import check_cycles
from cathedral_keeper.policies.dead_modules import check_dead_modules
from cathedral_keeper.policies.dependency_health import check_dependency_health
from cathedral_keeper.policies.drift import check_drift, compute_metrics, save_baseline
from cathedral_keeper.policies.env_parity import check_env_parity
from cathedral_keeper.policies.layer_direction import check_layer_direction
from cathedral_keeper.policies.service_boundaries import check_service_boundaries
from cathedral_keeper.policies.test_alignment import check_test_alignment
from cathedral_keeper.policies.test_coverage import check_test_coverage, detect_test_edges
from cathedral_keeper.python_graph import PyGraph, build_import_graph, build_module_index
from cathedral_keeper.python_imports import iter_python_files
from cathedral_keeper.python_roots import resolve_python_roots
from cathedral_keeper.red_team import run_red_team_checks
from cathedral_keeper.reporting import build_report, write_json, write_markdown


@dataclass(frozen=True, slots=True)
class RunResult:
    exit_code: int
    report_md: Path
    report_json: Path


def run(args: Any) -> int:
    root = _resolve_root(args.root)
    cfg = load_config(root=root, config_path=args.config)
    files = _resolve_targets(root=root, cfg=cfg, mode=str(args.mode), base=str(args.base), paths_from=args.paths_from)
    target_paths_file, rels = _write_target_paths_file(root=root, files=files)
    ctx = IntegrationContext(root=root, target_paths_file=target_paths_file, target_rel_paths=rels)
    findings = _run_checks(ctx=ctx, cfg=cfg, files=files, disable_qg=bool(args.no_qg), verbose=bool(args.verbose))

    # Blast-radius analysis (Phase 2)
    blast_radius_enabled = getattr(args, "blast_radius", False)
    if blast_radius_enabled:
        findings.extend(_run_blast_radius(root=root, cfg=cfg, files=files, rels=rels, verbose=bool(args.verbose)))

    top_findings = int(args.top) if args.top is not None else int(cfg.reporting.get("top_findings", 50))
    out_md, out_json = _resolve_outputs(root, args)
    report = build_report(root=root, findings=findings)
    write_markdown(report, out_md, top_findings=top_findings)
    write_json(report, out_json)

    threshold = str(cfg.thresholds.get("fail_on_severity_at_or_above", "high"))
    return _exit_code(findings, threshold=threshold)


def run_baseline(args: Any) -> int:
    """Create or update the architectural baseline snapshot."""
    root = _resolve_root(args.root)
    cfg = load_config(root=root, config_path=args.config)
    files = _resolve_targets(root=root, cfg=cfg, mode="repo", base="HEAD~1", paths_from=None)
    python_roots = resolve_python_roots(root, cfg.python_roots_config)

    metrics = compute_metrics(
        root=root, files=files, python_roots=python_roots, policies_cfg=cfg.policies,
    )

    drift_cfg = (cfg.policies.get("CK-ARCH-DRIFT") or {}).get("config") or cfg.policies.get("CK-ARCH-DRIFT") or {}
    baseline_rel = str(drift_cfg.get("baseline_path", ".quality-reports/cathedral-keeper/baseline.json"))
    baseline_path = root / baseline_rel

    path = save_baseline(root=root, metrics=metrics, baseline_path=baseline_path)
    print(f"[CK] Baseline saved to: {path}")
    print(f"[CK] Metrics: {len(files)} modules, {metrics['total_import_edges']} edges, "
          f"{metrics['cycle_count']} cycles, {metrics['dead_modules']} dead modules")
    return 0


def _run_blast_radius(
    *,
    root: Path,
    cfg: CKConfig,
    files: List[Path],
    rels: List[str],
    verbose: bool,
) -> List[Finding]:
    """Run blast-radius analysis on the target files.

    Builds the full import graph (not just target files), computes
    reverse-edge BFS from target files, and emits findings for
    high fan-in hotspots.
    """
    findings: List[Finding] = []
    python_roots = resolve_python_roots(root, cfg.python_roots_config)

    # Build full import graph (need all files for complete reverse index)
    all_files = list(iter_python_files(root))
    include = list(cfg.paths.get("include", []) or [])
    exclude = list(cfg.paths.get("exclude", []) or [])
    all_files = filter_paths(all_files, root=root, include=include, exclude=exclude)

    mod_index = build_module_index(root=root, python_roots=python_roots)
    graph = build_import_graph(root=root, files=all_files, module_index=mod_index)

    # Blast-radius config
    br_cfg = (cfg.policies.get("CK-BLAST-RADIUS") or {}).get("config") or {}
    max_depth = int(br_cfg.get("max_depth", 3))
    fan_in_threshold = int(br_cfg.get("fan_in_threshold", 10))

    # Compute blast radius for target files
    br = compute_blast_radius(graph, rels, max_depth=max_depth, include_tests=True)

    if verbose:
        total_affected = len(br.direct_dependents) + len(br.transitive_dependents)
        print(f"[CK] Blast radius: {len(rels)} changed -> {total_affected} affected files, {len(br.affected_tests)} tests")

    # Emit findings for high fan-in files among the changed files
    for changed_file in rels:
        fan_in = br.fan_in_scores.get(changed_file, 0)
        if fan_in >= fan_in_threshold:
            dependents = br.direct_dependents + br.transitive_dependents
            findings.append(
                Finding(
                    policy_id="CK-BLAST-RADIUS",
                    title=f"High fan-in file modified: {changed_file} (fan-in: {fan_in})",
                    severity="medium",
                    confidence="high",
                    why_it_matters=(
                        f"{changed_file} is imported by {fan_in} other files. "
                        f"Changes to it affect {len(dependents)} files in total. "
                        f"Review ALL callers and run FULL test suite."
                    ),
                    evidence=[
                        Evidence(
                            file=changed_file,
                            line=0,
                            snippet=f"fan-in={fan_in}, blast-radius={len(dependents)} files",
                            note=f"Direct: {len(br.direct_dependents)}, Transitive: {len(br.transitive_dependents)}, Tests: {len(br.affected_tests)}",
                        )
                    ],
                    fix_options=[
                        f"Review all {fan_in} callers of {changed_file} for compatibility.",
                        f"Run affected tests: {', '.join(br.affected_tests[:5])}{'...' if len(br.affected_tests) > 5 else ''}",
                    ],
                    verification=["ck analyze --root . --blast-radius --verbose"],
                    metadata={
                        "fan_in": fan_in,
                        "direct_dependents": br.direct_dependents[:20],
                        "transitive_dependents": br.transitive_dependents[:20],
                        "affected_tests": br.affected_tests[:20],
                        "blast_radius_total": len(dependents),
                    },
                )
            )

    # Also flag high fan-in files across the entire codebase (hotspot report)
    hotspots = identify_high_fan_in(graph, threshold=fan_in_threshold)
    if hotspots and verbose:
        print(f"[CK] High fan-in hotspots: {', '.join(f'{p}({c})' for p, c in hotspots[:5])}")

    return findings


def _resolve_root(arg_root: Optional[Path]) -> Path:
    if arg_root:
        return Path(arg_root).resolve()
    git_root = find_git_root(Path.cwd())
    return git_root.resolve() if git_root else Path.cwd().resolve()


def _resolve_outputs(root: Path, args: Any) -> Tuple[Path, Path]:
    out_dir = root / ".quality-reports" / "cathedral-keeper"
    md = Path(args.out_md).resolve() if args.out_md else (out_dir / "report.md")
    js = Path(args.out_json).resolve() if args.out_json else (out_dir / "report.json")
    return md, js


def _resolve_targets(
    *,
    root: Path,
    cfg: CKConfig,
    mode: str,
    base: str,
    paths_from: Optional[Path],
) -> List[Path]:
    include = list(cfg.paths.get("include", []) or [])
    exclude = list(cfg.paths.get("exclude", []) or [])
    exts = set([str(x).lower() for x in (cfg.paths.get("extensions", []) or [".py"])])

    if paths_from and paths_from.exists():
        items = [line.strip() for line in paths_from.read_text(encoding="utf-8", errors="ignore").splitlines()]
        files = [(root / line).resolve() for line in items if line]
        files = [p for p in files if p.exists() and p.is_file() and p.suffix.lower() in exts]
        return filter_paths(files, root=root, include=include, exclude=exclude)

    if mode == "diff":
        changed = git_changed_files(root=root, base=base)
        files = [(root / p).resolve() for p in changed]
        files = [p for p in files if p.exists() and p.is_file() and p.suffix.lower() in exts]
        return filter_paths(files, root=root, include=include, exclude=exclude)

    all_py = list(iter_python_files(root))
    all_py = [p for p in all_py if p.suffix.lower() in exts]
    return filter_paths(all_py, root=root, include=include, exclude=exclude)


def _run_checks(
    *,
    ctx: IntegrationContext,
    cfg: CKConfig,
    files: List[Path],
    disable_qg: bool,
    verbose: bool,
) -> List[Finding]:
    # Step 1: Integrations (QG, external tools)
    qg_findings = _run_integrations(ctx=ctx, cfg=cfg, disable_quality_gate=disable_qg)

    # Step 2: CK policies (cycles, boundaries, drift, test-coverage, etc.)
    ck_findings = _run_policies(root=ctx.root, cfg=cfg, files=files)

    findings: List[Finding] = qg_findings + ck_findings

    # Step 3: Cross-metric coherence check (Phase 1)
    if _enabled(cfg.policies, "CK-COHERENCE"):
        coherence_cfg = (cfg.policies.get("CK-COHERENCE") or {}).get("config") or {}
        coherence_cfg["file_count"] = len(files)
        findings.extend(check_coherence(
            qg_findings=qg_findings,
            ck_findings=ck_findings,
            config=coherence_cfg,
        ))

    # Step 4: Red team checks (Phase 4 — runs last, checks the checks)
    if _enabled(cfg.policies, "CK-RED-TEAM"):
        rt_cfg = (cfg.policies.get("CK-RED-TEAM") or {}).get("config") or {}
        findings.extend(run_red_team_checks(
            findings=findings,
            file_count=len(files),
            config=rt_cfg,
        ))

    if verbose:
        print(f"[CK] Files analyzed: {len(files)}")
        print(f"[CK] Findings: {len(findings)}")
    return findings


def _run_integrations(*, ctx: IntegrationContext, cfg: CKConfig, disable_quality_gate: bool) -> List[Finding]:
    enabled = parse_enabled_integrations(cfg.raw)
    findings: List[Finding] = []
    for integration_id, icfg in enabled.items():
        if disable_quality_gate and integration_id == "quality_gate":
            continue
        findings.extend(run_integration(ctx=ctx, integration_id=integration_id, cfg=icfg))
    return findings


def _run_policies(*, root: Path, cfg: CKConfig, files: List[Path]) -> List[Finding]:
    policies = cfg.policies
    python_roots = resolve_python_roots(root, cfg.python_roots_config)
    findings: List[Finding] = []
    if _enabled(policies, "CK-PY-CYCLES"):
        findings.extend(check_cycles(root=root, cfg=policies.get("CK-PY-CYCLES") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-PY-BOUNDARIES"):
        findings.extend(check_boundaries(root=root, cfg=policies.get("CK-PY-BOUNDARIES") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-LAYER-DIRECTION"):
        findings.extend(check_layer_direction(root=root, cfg=policies.get("CK-ARCH-LAYER-DIRECTION") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-DEAD-MODULES"):
        findings.extend(check_dead_modules(root=root, cfg=policies.get("CK-ARCH-DEAD-MODULES") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-SERVICE-BOUNDARIES"):
        findings.extend(check_service_boundaries(root=root, cfg=policies.get("CK-ARCH-SERVICE-BOUNDARIES") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-CONFIG-SPRAWL"):
        findings.extend(check_config_sprawl(root=root, cfg=policies.get("CK-ARCH-CONFIG-SPRAWL") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-TEST-ALIGNMENT"):
        findings.extend(check_test_alignment(root=root, cfg=policies.get("CK-ARCH-TEST-ALIGNMENT") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-ENV-PARITY"):
        findings.extend(check_env_parity(root=root, cfg=policies.get("CK-ARCH-ENV-PARITY") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-DEPENDENCY-HEALTH"):
        findings.extend(check_dependency_health(root=root, cfg=policies.get("CK-ARCH-DEPENDENCY-HEALTH") or {}, files=files, python_roots=python_roots))
    if _enabled(policies, "CK-ARCH-DRIFT"):
        findings.extend(check_drift(root=root, cfg=policies.get("CK-ARCH-DRIFT") or {}, files=files, python_roots=python_roots, policies_cfg=policies))
    if _enabled(policies, "CK-ARCH-TEST-COVERAGE"):
        tc_cfg = (policies.get("CK-ARCH-TEST-COVERAGE") or {}).get("config") or {}
        mod_index = build_module_index(root=root, python_roots=python_roots)
        graph = build_import_graph(root=root, files=files, module_index=mod_index)
        source_files = [
            normalize_path(str(f.resolve().relative_to(root.resolve())))
            for f in files
        ]
        findings.extend(check_test_coverage(graph=graph, source_files=source_files, cfg=tc_cfg))
    return findings


def _enabled(policies: dict, pid: str) -> bool:
    p = policies.get(pid) or {}
    return bool(p.get("enabled", False))


def _exit_code(findings: List[Finding], *, threshold: str) -> int:
    thr = severity_rank(threshold)
    worst = 0
    for f in findings:
        worst = max(worst, severity_rank(f.severity))
    return 1 if worst >= thr and thr > 0 else 0


def _write_target_paths_file(*, root: Path, files: List[Path]) -> Tuple[Path, List[str]]:
    out_dir = root / ".quality-reports" / "cathedral-keeper"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "paths.txt"
    rels = [str(p.resolve().relative_to(root.resolve())).replace("\\", "/") for p in files if p.exists()]
    path.write_text("\n".join(rels) + "\n", encoding="utf-8")
    return path, rels
