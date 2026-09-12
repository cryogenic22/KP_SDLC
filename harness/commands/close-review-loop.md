---
description: Classify review findings and turn reproduced escapes into bounded harness improvements.
---

Close the independent review using
`.claude/skills/review-convergence/SKILL.md` (or the engine source under
`harness/skills/`). Do not change code or policy while classifying.

Persist one `## Review learning record` comment on the PR (or its tracking
issue when no PR exists). Start it with the exact marker
`<!-- kp-sdlc-review-learning:v1 -->`, followed by one fenced JSON object with
this shape so Observatory/ACP can aggregate records without interpreting prose:

```json
{
  "schema_version": 1,
  "base_sha": "full SHA",
  "head_sha": "full SHA",
  "catalog_version": 1,
  "review_round": 1,
  "decision": "BLOCK",
  "author_first_time_success": false,
  "reviewer_first_pass_complete": true,
  "findings": [
    {
      "found_in_round": 1,
      "severity": "MAJOR",
      "classification": "ESCAPED",
      "pattern_id": "KP-RV-001",
      "prevention_point": "test-gate",
      "disposition": "Fixed at the reviewed head; planted failure now exits non-zero."
    }
  ]
}
```

Allowed decisions are `APPROVE`, `APPROVE-WITH-NITS`, and `BLOCK`. Allowed
severity, classification, and prevention-point values are the enums shown in
the review-convergence skill. Use JSON `null` for `pattern_id` only when the
classification is `NOVEL` or `FALSE-POSITIVE`.

Set `author_first_time_success` true only when the first independent review
found no `ESCAPED` pattern and no evidence omission the author could reasonably
have closed before handoff. A reproduced `NOVEL` finding does not make it false.
Set `reviewer_first_pass_complete` false when a later round finds a reasonably
foreseeable defect in unchanged code without new evidence. Post human-readable
detail after the JSON when useful; do not put commentary inside the object.

For every finding, report:

- finding and severity;
- classification: `KNOWN`, `ESCAPED`, `NOVEL`, or `FALSE-POSITIVE`;
- matching `KP-RV-*` ID, or why the root cause is genuinely absent;
- earliest prevention point: author handoff, test/gate, integration proof, or
  reviewer lens;
- disposition and evidence: fixed now, issue/PR with owner, or rejected after
  reproduction.

For each `ESCAPED` item, propose the smallest prevention improvement. For each
`NOVEL` item, reproduce it before proposing a catalog entry. A catalog update
must include a positive control, planted negative, applicability boundary, and
retirement condition.

End any human-readable detail with these counters:

```text
Review rounds:
Base SHA:
Reviewed head SHA:
Catalog version:
Decision:
KNOWN:
ESCAPED:
NOVEL:
FALSE-POSITIVE:
Harness actions opened:
```

Do not optimize these numbers by suppressing findings. Do not autonomously
apply, merge, waive, tighten, or weaken a control.
