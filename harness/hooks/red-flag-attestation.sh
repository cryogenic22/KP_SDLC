#!/usr/bin/env bash
# Red-flag attestation — pre-commit (prepare-commit-msg) hook.
#
# Appends a `### Self-review` skeleton to the commit message if missing.
# The agent fills it in based on .claude/skills/design-philosophy/SKILL.md
# Tier 2 (22 red flags from Ousterhout + Pragmatic + Karpathy).
#
# Non-blocking by design — invites attention rather than enforcing it.
# The CI second-pass-reviewer audits attestations vs the actual diff.
#
# pre-commit invokes with: $1 = path to commit message file
#                          $2 = source ("message", "template", "merge", "squash", "commit", or "")
#                          $3 = sha (only when $2 is "commit")
set -euo pipefail

MSG_FILE="${1:-}"
SOURCE="${2:-}"

# No commit message file (shouldn't happen) — exit silently.
[[ -z "$MSG_FILE" || ! -f "$MSG_FILE" ]] && exit 0

# Skip merge / squash / amend (the message is already authored by humans
# or built from earlier commits — re-attestation isn't useful here).
case "$SOURCE" in
  merge|squash|commit) exit 0 ;;
esac

# If a Self-review block is already present, leave it alone.
if grep -q "^### Self-review" "$MSG_FILE" 2>/dev/null; then
  exit 0
fi

# Append the skeleton. Use literal heredoc to avoid expansion of $ inside.
cat >> "$MSG_FILE" <<'EOF'

### Self-review (Tier 2 — fill in or delete with reason)

Walk the 22-item checklist in .claude/skills/design-philosophy/SKILL.md.
Mark each PASS / N/A / FIXED / JUSTIFIED. Delete this entire block if the
change is trivial (typo, lockfile fixup) and the omission is explained
elsewhere in this commit body.

Ousterhout (13): shallow-module · info-leakage · temporal-decomp · over-
exposure · pass-through · repetition · special-general-mix · conjoined ·
comment-repeats-code · impl-leaks-interface · vague-name · hard-to-describe
· hard-to-name

Pragmatic (5): broken-window · resource-leak · silent-failure · untested ·
premature-abstraction

Karpathy (4): unstated-assumption · off-task · speculative-feature · weak-
success-criterion

Summary: __PASS · __N/A · __FIXED · __JUSTIFIED
EOF

exit 0
