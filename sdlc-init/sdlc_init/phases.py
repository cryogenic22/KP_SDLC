"""The ordered init phases. Each takes the InitContext, does idempotent work,
and returns a PhaseResult. The golden path is:

  copy_harness → park_config_workflows → setup_floor → write_manifest

with optional onboard_ctxpack and born_gated_fixture composed by the CLI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import harness_map as hm
from .executor import (InitContext, PhaseResult, assert_no_residual_placeholders,
                       install_file)
from .manifest import build_repo_manifest, write_repo_manifest


def _dest_for_workflow(filename: str) -> str:
    """Config-carrying workflows go to workflows-parked/; the rest are active."""
    base = f"{hm.WORKFLOWS_PARKED}" if filename in hm.CONFIG_WORKFLOWS else hm.WORKFLOWS_DEST
    return f"{base}/{filename}"


def _install_skills(ctx: InitContext) -> list[str]:
    """Copy each harness skill directory whole (skip a skill already present)."""
    changes: list[str] = []
    skills_src = ctx.harness_dir / hm.SKILLS_SRC
    if not skills_src.is_dir():
        return changes
    for skill in sorted(p for p in skills_src.iterdir() if p.is_dir()):
        if (ctx.target / hm.SKILLS_DEST / skill.name).exists():
            continue
        for f in sorted(skill.rglob("*")):
            if not f.is_file():
                continue
            rel = f"{hm.SKILLS_DEST}/{skill.name}/{f.relative_to(skill).as_posix()}"
            if install_file(ctx, f, rel):
                changes.append(rel)
    return changes


def _install_files(ctx: InitContext) -> list[str]:
    """Copy the explicit FILE_MAP entries."""
    changes: list[str] = []
    for src_rel, dest_rel in hm.FILE_MAP:
        src = ctx.harness_dir / src_rel
        if src.is_file() and install_file(ctx, src, dest_rel):
            changes.append(dest_rel)
    return changes


def _install_dirs(ctx: InitContext) -> list[str]:
    """Copy the DIR_MAP fan-outs; route CI workflows by park classification."""
    changes: list[str] = []
    for src_dir_rel, dest_dir_rel in hm.DIR_MAP:
        src_dir = ctx.harness_dir / src_dir_rel
        if not src_dir.is_dir():
            continue
        for f in sorted(p for p in src_dir.iterdir() if p.is_file()):
            name = f.name[:-5] if f.name.endswith(".tmpl") else f.name
            dest_rel = (_dest_for_workflow(name) if src_dir_rel == "ci"
                        else f"{dest_dir_rel}/{name}")
            if install_file(ctx, f, dest_rel):
                changes.append(dest_rel)
    return changes


def copy_harness(ctx: InitContext) -> PhaseResult:
    """Install skills, files, and directory fan-outs from the harness. Parks
    config-carrying workflows and asserts no active file ships a placeholder."""
    changes = _install_skills(ctx) + _install_files(ctx) + _install_dirs(ctx)

    # Anti-case: no active workflow may carry an unfilled placeholder.
    for dest_rel in changes:
        if dest_rel.startswith(hm.WORKFLOWS_DEST + "/"):
            assert_no_residual_placeholders(ctx, dest_rel)

    return PhaseResult("copy_harness", "dry" if ctx.dry_run else "ok",
                       detail="harness installed", changes=changes)


def park_readme(ctx: InitContext) -> PhaseResult:
    """Explain why parked workflows are parked (idempotent)."""
    parked_dir = ctx.target / hm.WORKFLOWS_PARKED
    if ctx.dry_run or not parked_dir.exists():
        return PhaseResult("park_readme", "dry" if ctx.dry_run else "skip")
    readme = parked_dir / "README.md"
    if readme.exists():
        return PhaseResult("park_readme", "skip")
    parked = sorted(p.name for p in parked_dir.glob("*.yml"))
    lines = [
        "# Parked workflow templates",
        "",
        "These gates ship with the harness but are parked until the stack they",
        "gate exists — raw `{{PLACEHOLDER}}` values are invalid workflow YAML,",
        "and a gate that runs against nothing is vacuous green.",
        "",
        *[f"- `{name}` — fill its placeholders, move to `{hm.WORKFLOWS_DEST}/`, "
          f"and add a deliberately failing fixture in the activating PR to prove "
          f"it fires." for name in parked],
        "",
    ]
    readme.write_text("\n".join(lines), encoding="utf-8")
    rel = f"{hm.WORKFLOWS_PARKED}/README.md"
    return PhaseResult("park_readme", "ok", changes=[rel])


def setup_floor(ctx: InitContext) -> PhaseResult:
    """Generate CODEOWNERS from the (now owner-filled) protected surface and
    prove surface↔CODEOWNERS are in sync. Reuses the shipped gen_codeowners.py
    rather than reimplementing it."""
    if ctx.dry_run:
        return PhaseResult("setup_floor", "dry", detail="would generate CODEOWNERS")
    gen = ctx.target / "scripts" / "gen_codeowners.py"
    surface = ctx.target / "protected-surface.txt"
    if not gen.exists() or not surface.exists():
        return PhaseResult("setup_floor", "fail",
                           detail="gen_codeowners.py or protected-surface.txt missing")
    gen_out = subprocess.run([sys.executable, str(gen)], cwd=str(ctx.target),
                             capture_output=True, text=True)
    if gen_out.returncode != 0:
        return PhaseResult("setup_floor", "fail", detail=gen_out.stderr.strip()[:200])
    check = subprocess.run([sys.executable, str(gen), "--check"], cwd=str(ctx.target),
                           capture_output=True, text=True)
    status = "ok" if check.returncode == 0 else "fail"
    return PhaseResult("setup_floor", status, detail="CODEOWNERS generated + in sync",
                       changes=[".github/CODEOWNERS"])


def write_manifest(ctx: InitContext) -> PhaseResult:
    """Emit .harness/manifest.json — the engine-pin + provenance record.
    Reads the prior phase outcomes accumulated on ctx.results."""
    if ctx.dry_run:
        return PhaseResult("write_manifest", "dry", detail="would write .harness/manifest.json")
    manifest = build_repo_manifest(ctx.manifest, ctx.as_of, [r.as_dict() for r in ctx.results])
    dest = write_repo_manifest(ctx.target, manifest)
    sha = manifest["engine"]["sha"]
    if sha == "unknown":
        ctx.log("  [warn] engine SHA could not be resolved (engine_root is not a "
                "git checkout) — the repo is NOT pinned to a specific engine commit.")
        detail = "engine SHA unknown — not pinned"
    else:
        detail = f"engine pinned @ {sha[:8]}"
    return PhaseResult("write_manifest", "ok", detail=detail, changes=[ctx.rel(dest)])
