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
]

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
