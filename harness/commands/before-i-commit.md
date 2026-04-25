---
description: Full pre-commit attestation walkthrough. Run /review then /entropy-check, then verify the commit message has a Self-review block.
---

Before committing, do all three:

1. **Run the red-flag review.** Walk all 22 flags in `.claude/skills/design-philosophy/SKILL.md` Tier 2 against the staged diff. Mark each PASS / N/A / FIXED / JUSTIFIED.

2. **Run an entropy check.** Scan the working tree for broken windows (see `/entropy-check` for the catalogue). Resolve each: fix / ticket / accept-with-comment.

3. **Verify the commit message.** Open the staged commit message (run `git diff --cached` and check what's about to commit). The body should:
   - Cite the spec or issue if applicable (`Implements specs/NNNN-...`).
   - Have a `### Self-review` block — the `red-flag-attestation` hook will scaffold one if missing. Fill it in honestly. Mark FIXED items separately so reviewers can find them.
   - Avoid the words "comprehensive", "robust", "production-ready" in the body — they're noise.

End by reporting:
- Total flags reviewed: X PASS · Y N/A · Z FIXED · W JUSTIFIED
- Broken windows resolved: N (and how — fix / ticket / accept)
- Commit message status: ready / needs Self-review block / needs spec citation

If any of the three returns a FIXED that requires a code change, do that change first, re-stage, and re-run this command.
