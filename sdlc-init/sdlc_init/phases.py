"""The ordered init phases. Each takes the InitContext, does idempotent work,
and returns a PhaseResult. The golden path is:

  copy_harness → park_readme → vendor_engine → setup_floor
    → born_gated_proof → write_manifest

with optional onboard_ctxpack composed by the CLI.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterator

from . import harness_map as hm
from .executor import (InitContext, PhaseResult, assert_no_residual_placeholders,
                       install_file)
from .manifest import build_repo_manifest, write_repo_manifest


def _dest_for_workflow(ctx: InitContext, filename: str) -> str:
    """Parked workflows go to workflows-parked/; the rest are active. The
    parked set rides on the context: init parks the config-carrying trio,
    bootstrap additionally parks engine-gates.yml (it never vendors the
    tools/qa engines that workflow runs)."""
    base = hm.WORKFLOWS_PARKED if filename in ctx.parked_workflows else hm.WORKFLOWS_DEST
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
            dest_rel = (_dest_for_workflow(ctx, name) if src_dir_rel == "ci"
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

    # A pre-existing .claude/settings.json is user-owned and never clobbered
    # (skip-if-exists), but that means the PreToolUse hook wiring was NOT
    # applied — surface it, or the pipeline table is silently aspirational
    # for exactly this repo.
    detail = "harness installed"
    settings_dest = ".claude/settings.json"
    if (not ctx.dry_run and settings_dest not in changes
            and any(dest == settings_dest for _src, dest in hm.FILE_MAP)
            and (ctx.target / settings_dest).exists()):
        detail += (f"; skipped {settings_dest} (pre-existing, left untouched) — "
                   "PreToolUse hook wiring not applied; add the hooks block "
                   "from harness/templates/claude-settings.json.tmpl manually")

    return PhaseResult("copy_harness", "dry" if ctx.dry_run else "ok",
                       detail=detail, changes=changes)


def _parked_reason(name: str) -> str:
    """Per-workflow README line: engine-gates.yml is parked only on the
    copy-only bootstrap path (its placeholders ARE filled — what is missing
    is the vendored engine it runs); the rest wait on config placeholders."""
    if name == "engine-gates.yml":
        return (f"- `{name}` — parked because this repo was bootstrapped "
                f"copy-only: the `tools/qa/` engines it runs were never "
                f"vendored. Vendor them (`sdlc init` does this end-to-end), "
                f"then move it to `{hm.WORKFLOWS_DEST}/`.")
    return (f"- `{name}` — fill its placeholders, move to `{hm.WORKFLOWS_DEST}/`, "
            f"and add a deliberately failing fixture in the activating PR to prove "
            f"it fires.")


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
        *[_parked_reason(name) for name in parked],
        "",
    ]
    readme.write_text("\n".join(lines), encoding="utf-8")
    rel = f"{hm.WORKFLOWS_PARKED}/README.md"
    return PhaseResult("park_readme", "ok", changes=[rel])


def _missing_vendor_sources(engine_root: Path) -> list[str]:
    """Engine components the vendor maps expect but the checkout lacks."""
    missing = [src for src, _ in hm.ENGINE_VENDOR_MAP
               if not (engine_root / src).is_file()]
    missing += [src for src, _ in hm.ENGINE_VENDOR_DIRS
                if not (engine_root / src).is_dir()]
    return missing


def _iter_vendor_files(engine_root: Path) -> Iterator[tuple[Path, str]]:
    """Yield (source, dest_rel) for every file to vendor: the explicit map,
    then the directory fan-outs filtered to code+config and pruned of
    caches/tests (which also sidesteps stray non-code files like 'nul')."""
    for src_rel, dest_rel in hm.ENGINE_VENDOR_MAP:
        yield engine_root / src_rel, dest_rel
    for src_dir_rel, dest_dir_rel in hm.ENGINE_VENDOR_DIRS:
        src_dir = engine_root / src_dir_rel
        for f in sorted(src_dir.rglob("*")):
            if not f.is_file() or f.suffix not in hm.VENDOR_INCLUDE_SUFFIXES:
                continue
            rel = f.relative_to(src_dir)
            if hm.VENDOR_PRUNE_DIRS & set(rel.parts):
                continue
            yield f, f"{dest_dir_rel}/{rel.as_posix()}"


def vendor_engine(ctx: InitContext) -> PhaseResult:
    """Vendor the pinned QG+CK engines into tools/qa/ — BYTE-copied (never
    install_file: substitution or LF-forcing would corrupt the sha256 pin),
    skip-if-exists (a locally modified vendored file is drift for `sdlc
    status` to surface, never something init clobbers), and hashed per file
    for the manifest's engine.vendored record."""
    if ctx.dry_run:
        return PhaseResult("vendor_engine", "dry",
                           detail=f"would vendor QG+CK into {hm.ENGINE_VENDOR_DEST}/")
    missing = _missing_vendor_sources(ctx.manifest.engine_root)
    if missing:
        return PhaseResult("vendor_engine", "fail",
                           detail="engine components not found — cannot vendor: "
                                  + ", ".join(missing))
    changes: list[str] = []
    for src, dest_rel in _iter_vendor_files(ctx.manifest.engine_root):
        data = src.read_bytes()
        ctx.vendor_hashes[dest_rel] = hashlib.sha256(data).hexdigest()
        dest = ctx.target / dest_rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        changes.append(dest_rel)
    detail = (f"vendored {len(ctx.vendor_hashes)} engine files into "
              f"{hm.ENGINE_VENDOR_DEST}/ ({len(changes)} new)")
    return PhaseResult("vendor_engine", "ok", detail=detail, changes=changes)


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


_FIXTURE_REL = ".harness/proof/born_gated_fixture.py"


def bad_fixture_source() -> str:
    """A known-bad snippet that deterministically trips >=1 QG error (the
    heartbeat discipline of qg/tool_status.py: a hardcoded secret + a silent
    catch). Assembled from pieces so the engine's own scan of THIS file never
    matches the patterns it plants."""
    secret = "pass" + 'word = "hunter2hunter2"'
    silent = "try:\n    risky()\nexcept" + ":\n    pass\n"
    return secret + "\n" + silent


def _run_gate(ctx: InitContext, args: list[str], extra: list[str]) -> subprocess.CompletedProcess:
    """Run a vendored gate with the SAME argv the engine-gates workflow uses
    (single-sourced in harness_map), from the target root. Bytecode caching
    is disabled so the proof leaves no __pycache__ residue in the vendor tree
    (the manifest's per-file record must keep matching the tree exactly)."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, *args, *extra], cwd=str(ctx.target),
                          capture_output=True, text=True, env=env)


def _prove_fixture_caught(ctx: InitContext) -> str | None:
    """Plant the known-bad fixture, require QG exit 1 on it, remove it.
    Returns an error detail, or None when the red side of the proof holds."""
    fixture = ctx.target / _FIXTURE_REL
    try:
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(bad_fixture_source(), encoding="utf-8", newline="\n")
        planted = _run_gate(ctx, hm.QG_GATE_ARGS, [_FIXTURE_REL])
    finally:
        with contextlib.suppress(OSError):  # leave no residue
            fixture.unlink(missing_ok=True)
            fixture.parent.rmdir()  # only removed while empty
    if planted.returncode != 1:
        return (f"planted fixture NOT caught (QG exit {planted.returncode}, "
                f"expected 1) — the gate does not fire")
    return None


def _prove_ck_smoke(ctx: InitContext) -> str | None:
    """CK must run green with the shipped config and find the vendored QG.
    Returns an error detail, or None when the smoke holds."""
    ck = _run_gate(ctx, hm.CK_GATE_ARGS, [])
    if ck.returncode != 0:
        return f"CK smoke failed (exit {ck.returncode}): {ck.stderr.strip()[:160]}"
    report = ctx.target / ".quality-reports" / "cathedral-keeper" / "report.json"
    if not report.exists():
        return "CK smoke wrote no report.json"
    if "Quality Gate script not found" in report.read_text(encoding="utf-8"):
        return ("CK could not find the vendored QG — qg_path miswired in "
                ".cathedral-keeper.json")
    return None


def born_gated_proof(ctx: InitContext) -> PhaseResult:
    """Prove the born gate actually fires before declaring success: clean
    scan green → planted known-bad fixture caught (exit 1) → CK smoke green.
    Fails closed: a proof that cannot run must not pass."""
    if ctx.dry_run:
        return PhaseResult("born_gated_proof", "dry",
                           detail="would prove QG catches a planted fixture + CK smoke")
    if not all((ctx.target / a[0]).is_file() for a in (hm.QG_GATE_ARGS, hm.CK_GATE_ARGS)):
        return PhaseResult("born_gated_proof", "fail",
                           detail=f"vendored gate missing under {hm.ENGINE_VENDOR_DEST}/ "
                                  "— a proof that cannot run must not pass")
    clean = _run_gate(ctx, hm.QG_GATE_ARGS, [])
    if clean.returncode != 0:
        return PhaseResult("born_gated_proof", "fail",
                           detail=f"clean scan not green (QG exit {clean.returncode}) "
                                  "— the repo is not green from birth")
    error = _prove_fixture_caught(ctx) or _prove_ck_smoke(ctx)
    if error:
        return PhaseResult("born_gated_proof", "fail", detail=error)
    return PhaseResult("born_gated_proof", "ok",
                       detail="clean scan green; QG exit 1 on planted fixture; CK smoke ok")


def write_manifest(ctx: InitContext) -> PhaseResult:
    """Emit .harness/manifest.json — the engine-pin + provenance record.
    Reads the prior phase outcomes accumulated on ctx.results."""
    if ctx.dry_run:
        return PhaseResult("write_manifest", "dry", detail="would write .harness/manifest.json")
    manifest = build_repo_manifest(ctx.manifest, ctx.as_of, [r.as_dict() for r in ctx.results],
                                   vendor_hashes=ctx.vendor_hashes)
    dest = write_repo_manifest(ctx.target, manifest)
    sha = manifest["engine"]["sha"]
    if sha == "unknown":
        ctx.log("  [warn] engine SHA could not be resolved (engine_root is not a "
                "git checkout) — the repo is NOT pinned to a specific engine commit.")
        detail = "engine SHA unknown — not pinned"
    else:
        detail = f"engine pinned @ {sha[:8]}"
    return PhaseResult("write_manifest", "ok", detail=detail, changes=[ctx.rel(dest)])
