"""The harness file-map — the single declarative source of what a born-gated
repo receives and where. Both `sdlc init` (the Python executor) and the thin
`bootstrap.sh` shim consume this, so the mapping lives in exactly one place
(previously it was duplicated inside bootstrap.sh — the dispersion this
component exists partly to remove).
"""

from __future__ import annotations

# Skills: every directory under harness/skills/ → .claude/skills/<name>/
SKILLS_SRC = "skills"
SKILLS_DEST = ".claude/skills"

# Explicit file map: (source relative to harness/, dest relative to repo root).
# A trailing ".tmpl" on the source is stripped from the destination.
FILE_MAP: list[tuple[str, str]] = [
    ("templates/CLAUDE.md.tmpl", "CLAUDE.md"),
    ("templates/AGENTS.md.tmpl", "AGENTS.md"),
    ("templates/gitignore.tmpl", ".gitignore"),
    ("templates/gitattributes.tmpl", ".gitattributes"),
    ("templates/PULL_REQUEST_TEMPLATE.md.tmpl", ".github/PULL_REQUEST_TEMPLATE.md"),
    ("templates/claude-settings.json.tmpl", ".claude/settings.json"),
    ("hooks/pre-commit-config.yaml.tmpl", ".pre-commit-config.yaml"),
    ("hooks/red-flag-attestation.sh", ".harness/hooks/red-flag-attestation.sh"),
    ("hooks/second_pass_reviewer.py", ".harness/hooks/second_pass_reviewer.py"),
    ("hooks/reuse_injector.py", ".harness/hooks/reuse_injector.py"),
    ("process/check_pr_template.py", ".github/scripts/check_pr_template.py"),
    ("structural-floor/gen_codeowners.py", "scripts/gen_codeowners.py"),
    ("structural-floor/protected-surface.txt.tmpl", "protected-surface.txt"),
    ("structural-floor/test_protected_surface_sync.py.tmpl", "tests/test_protected_surface_sync.py"),
    ("templates/quality-gate.json.tmpl", ".quality-gate.json"),
    ("templates/cathedral-keeper.json.tmpl", ".cathedral-keeper.json"),
]

# Directory fan-outs: (source dir relative to harness/, dest dir in repo).
# Every file in the source dir is copied; ".tmpl" stripped.
DIR_MAP: list[tuple[str, str]] = [
    ("commands", ".claude/commands"),
    ("ci", ".github/workflows"),
    ("scripts", "scripts"),
    ("decisions", "docs/decisions"),
]

WORKFLOWS_DEST = ".github/workflows"
WORKFLOWS_PARKED = ".github/workflows-parked"

# Files whose pre-existence means the target is not a clean birth: `sdlc init`
# generates/owns them, so a pre-existing copy is user content init must not
# clobber (CODEOWNERS) or silently shadow (CLAUDE.md). init refuses when any is
# present *unless* the repo already carries our manifest (an init re-run). Layer
# the harness into an existing repo with `sdlc bootstrap` instead.
GATING_FILES: list[str] = [
    "CLAUDE.md",
    "AGENTS.md",
    "protected-surface.txt",
    ".github/CODEOWNERS",
    ".quality-gate.json",
]

# ── Engine vendoring (D1: vendored pinned copy) ──────────────────────
# Sources below are relative to the ENGINE ROOT (the KP_SDLC checkout), NOT
# to harness/ like FILE_MAP — the QG/CK engines live beside harness/, so they
# get their own constants rather than overloading FILE_MAP semantics.
# Vendored files are BYTE-copied (no substitution, no newline translation):
# the per-file sha256 recorded in .harness/manifest.json is only meaningful
# if the copy is byte-identical to the pinned engine source.
ENGINE_VENDOR_DEST = "tools/qa"

ENGINE_VENDOR_MAP: list[tuple[str, str]] = [
    ("quality-gate/quality_gate.py",
     "tools/qa/quality-gate/quality_gate.py"),
    ("quality-gate/quality-gate.config.json",
     "tools/qa/quality-gate/quality-gate.config.json"),
    ("cathedral-keeper/ck.py",
     "tools/qa/cathedral-keeper/ck.py"),
    ("cathedral-keeper/cathedral-keeper.config.json",
     "tools/qa/cathedral-keeper/cathedral-keeper.config.json"),
]

# Directory fan-outs, filtered: only VENDOR_INCLUDE_SUFFIXES files, pruning
# VENDOR_PRUNE_DIRS. The filter is load-bearing — a wholesale copy would ship
# __pycache__/, test trees, and the stray 0-byte Windows-reserved 'nul' file.
ENGINE_VENDOR_DIRS: list[tuple[str, str]] = [
    ("quality-gate/qg", "tools/qa/quality-gate/qg"),
    ("cathedral-keeper/cathedral_keeper", "tools/qa/cathedral-keeper/cathedral_keeper"),
]
VENDOR_INCLUDE_SUFFIXES: tuple[str, ...] = (".py", ".json")
VENDOR_PRUNE_DIRS: frozenset[str] = frozenset({"__pycache__", "tests"})

# Engine-gate command lines, single-sourced: harness/ci/engine-gates.yml.tmpl
# carries exactly these strings (a sync test enforces it) and born_gated_proof
# runs the same argv, so the local proof and the CI gate cannot drift.
# '--root .' is REQUIRED: the vendored QG defaults its root to tools/qa
# (script_dir.parent), which mis-anchors excludes and root-config discovery.
QG_GATE_ARGS: list[str] = [
    "tools/qa/quality-gate/quality_gate.py",
    "--root", ".", "--config", ".quality-gate.json", "--json",
]
QG_GATE_CMD: str = "python " + " ".join(QG_GATE_ARGS) + " --sarif qg.sarif"
CK_GATE_ARGS: list[str] = [
    "tools/qa/cathedral-keeper/ck.py",
    "analyze", "--root", ".", "--blast-radius",
]
CK_GATE_CMD: str = "python " + " ".join(CK_GATE_ARGS)

# Workflows that carry config placeholders no generic init can fill (they gate
# a stack that does not exist yet). They are copied to workflows-parked/ instead
# of workflows/, because a workflow with raw {{PLACEHOLDER}} values is invalid
# YAML on GitHub and a gate that runs against nothing is vacuous green. Keyed by
# destination filename (".tmpl" already stripped).
CONFIG_WORKFLOWS: frozenset[str] = frozenset({"quality.yml", "eval.yml", "web.yml"})


def substitutions(*, project_name: str, owner: str, as_of: str) -> dict[str, str]:
    """Placeholder → value map applied to every copied text file. Anything
    still matching ``{{...}}`` after this is an unfilled placeholder and the
    copy phase routes/flags it rather than shipping invalid output."""
    return {
        "{{PROJECT_NAME}}": project_name,
        "{{OWNER}}": owner,
        "{{BOOTSTRAP_DATE}}": as_of,
    }
