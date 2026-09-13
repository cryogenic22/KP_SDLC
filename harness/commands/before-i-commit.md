---
description: Full pre-commit attestation: handoff invariants, review, entropy check, and commit-message verification.
---

Before committing, do all four:

1. **Build the handoff.** State change risk, invariants, applicable `KP-RV-*`
   patterns from `.claude/skills/review-convergence/SKILL.md`, and the negative
   proof. For low-risk changes, `N/A` still needs a concrete reason.

2. **Run the review.** Complete the seven assurance lenses, then walk all 22
   flags in `.claude/skills/design-philosophy/SKILL.md` Tier 2 against the staged
   diff. Mark each PASS / N/A / FIXED / JUSTIFIED.

3. **Run an entropy check.** Scan the working tree for broken windows (see
   `/entropy-check`). Resolve each as fix, ticket, or accept with a comment.

4. **Verify the commit message.** Inspect `git diff --cached`. The body should:
   - cite the spec or issue when applicable;
   - have a `### Self-review` block (the `red-flag-attestation` hook scaffolds
     one when missing), with FIXED items called out;
   - avoid "comprehensive", "robust", and "production-ready" because they do
     not constitute evidence.

End by reporting:

- change risk, invariants, catalog patterns, and negative proof;
- assurance sweep status;
- Tier 2 totals: X PASS / Y N/A / Z FIXED / W JUSTIFIED;
- broken windows resolved and their disposition;
- commit-message status.

If review finds a defect requiring a code change, make the change, restage, and
rerun the entire assurance sweep rather than only the edited lens.
