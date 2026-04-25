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

# ---- top-level templates: CLAUDE.md, AGENTS.md ---------------------------
for tmpl in CLAUDE.md AGENTS.md; do
  src="$HARNESS_DIR/templates/${tmpl}.tmpl"
  dest="$TARGET_DIR/$tmpl"
  [[ -f "$src" ]] || continue
  if [[ -f "$dest" ]]; then
    note_skip "$tmpl"
  else
    # Substitute placeholders. {{PROJECT_NAME}} stays unresolved (user fills),
    # {{BOOTSTRAP_DATE}} is filled now.
    sed "s/{{BOOTSTRAP_DATE}}/$TODAY/g" "$src" > "$dest"
    note_add "$tmpl"
  fi
done

# ---- subdirs (T2/T3 components — bootstrap honours whatever is present) --
declare -A SUBDIR_TARGETS=(
  [commands]=".claude/commands"
  [ci]=".github/workflows"
  [hooks]=".harness/hooks"
  [scripts]="scripts"
  [decisions]="docs/decisions"
)

for component in "${!SUBDIR_TARGETS[@]}"; do
  src_dir="$HARNESS_DIR/$component"
  [[ -d "$src_dir" ]] || continue

  shopt -s nullglob
  files=( "$src_dir"/* )
  shopt -u nullglob
  [[ ${#files[@]} -gt 0 ]] || continue

  target_subdir="${SUBDIR_TARGETS[$component]}"
  mkdir -p "$TARGET_DIR/$target_subdir"

  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    bn="$(basename "$f")"
    dest_name="${bn%.tmpl}"
    dest="$TARGET_DIR/$target_subdir/$dest_name"
    if [[ -e "$dest" ]]; then
      note_skip "$target_subdir/$dest_name"
    else
      if [[ "$bn" == *.tmpl ]]; then
        sed "s/{{BOOTSTRAP_DATE}}/$TODAY/g" "$f" > "$dest"
      else
        cp "$f" "$dest"
      fi
      note_add "$target_subdir/$dest_name"
    fi
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
