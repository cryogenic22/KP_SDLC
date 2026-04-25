#!/usr/bin/env bash
# kp-sdlc harness bootstrap — installs the agent-facing layer into a target project.
#
# Idempotent: existing files are skipped (never overwritten silently). To force
# overwrite: delete the destination first, then re-run.
#
# Usage:
#   bash <KP_SDLC>/harness/bootstrap.sh                   # bootstrap into cwd
#   bash <KP_SDLC>/harness/bootstrap.sh /path/to/project  # explicit target
#
# After bootstrap:
#   1. Edit CLAUDE.md and AGENTS.md — replace {{PROJECT_NAME}} and {{BOOTSTRAP_DATE}}
#   2. Review .claude/skills/design-philosophy/SKILL.md
#   3. Add project-specific addenda in CLAUDE.md's <!-- project-specific --> block
#
set -euo pipefail

HARNESS_DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd )"
TARGET_DIR="${1:-$(pwd)}"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
TODAY="$(date +%Y-%m-%d)"

echo "[kp-sdlc harness] source : $HARNESS_DIR"
echo "[kp-sdlc harness] target : $TARGET_DIR"
echo "[kp-sdlc harness] date   : $TODAY"
echo

added=0
skipped=0

note_add()  { echo "  [add ] $1"; added=$((added + 1)); }
note_skip() { echo "  [skip] $1 (exists)"; skipped=$((skipped + 1)); }

# ---- skills --------------------------------------------------------------
mkdir -p "$TARGET_DIR/.claude/skills"
for skill_src in "$HARNESS_DIR"/skills/*/; do
  [[ -d "$skill_src" ]] || continue
  skill_name="$(basename "$skill_src")"
  dest="$TARGET_DIR/.claude/skills/$skill_name"
  if [[ -d "$dest" ]]; then
    note_skip ".claude/skills/$skill_name"
  else
    cp -r "$skill_src" "$dest"
    note_add ".claude/skills/$skill_name"
  fi
done

# ---- per-file mapping (templates and hooks go to explicit destinations) --
# Format: <source-relative-to-harness>|<destination-relative-to-target-root>
# .tmpl suffix is stripped; {{BOOTSTRAP_DATE}} substituted at copy.
FILE_MAP=(
  "templates/CLAUDE.md.tmpl|CLAUDE.md"
  "templates/AGENTS.md.tmpl|AGENTS.md"
  "templates/PULL_REQUEST_TEMPLATE.md.tmpl|.github/PULL_REQUEST_TEMPLATE.md"
  "hooks/pre-commit-config.yaml.tmpl|.pre-commit-config.yaml"
  "hooks/red-flag-attestation.sh|.harness/hooks/red-flag-attestation.sh"
  "hooks/second_pass_reviewer.py|.harness/hooks/second_pass_reviewer.py"
)

copy_file() {
  local src="$1" dest="$2"
  [[ -f "$src" ]] || return 0
  if [[ -f "$dest" ]]; then
    note_skip "${dest#$TARGET_DIR/}"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [[ "$src" == *.tmpl ]]; then
    sed "s/{{BOOTSTRAP_DATE}}/$TODAY/g" "$src" > "$dest"
  else
    cp "$src" "$dest"
  fi
  # Preserve executable bit for shell scripts.
  [[ "$src" == *.sh ]] && chmod +x "$dest"
  note_add "${dest#$TARGET_DIR/}"
}

for entry in "${FILE_MAP[@]}"; do
  src_rel="${entry%%|*}"
  dest_rel="${entry##*|}"
  copy_file "$HARNESS_DIR/$src_rel" "$TARGET_DIR/$dest_rel"
done

# ---- per-directory mapping (whole-dir fan-outs) --------------------------
declare -A DIR_TARGETS=(
  [commands]=".claude/commands"
  [ci]=".github/workflows"
  [scripts]="scripts"
  [decisions]="docs/decisions"
)

for component in "${!DIR_TARGETS[@]}"; do
  src_dir="$HARNESS_DIR/$component"
  [[ -d "$src_dir" ]] || continue

  shopt -s nullglob
  files=( "$src_dir"/* )
  shopt -u nullglob
  [[ ${#files[@]} -gt 0 ]] || continue

  target_subdir="${DIR_TARGETS[$component]}"

  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    bn="$(basename "$f")"
    dest_name="${bn%.tmpl}"
    copy_file "$f" "$TARGET_DIR/$target_subdir/$dest_name"
  done
done

echo
echo "[kp-sdlc harness] complete: $added added, $skipped skipped."
echo
echo "Next steps:"
echo "  1. Replace {{PROJECT_NAME}} in CLAUDE.md and AGENTS.md."
echo "  2. Read .claude/skills/design-philosophy/SKILL.md once."
echo "  3. Add project-specific addenda under <!-- project-specific -->."
echo "  4. Re-run this script after KP_SDLC harness updates — only new files are added."
