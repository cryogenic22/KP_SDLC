---
description: Run the 22-item Tier 2 red-flag checklist against the current diff (staged + unstaged + recent commits if asked).
---

Review the current diff against the 22 red flags in `.claude/skills/design-philosophy/SKILL.md` Tier 2.

If no scope is provided, default to staged + unstaged changes (`git diff HEAD`). If a scope is given (e.g. "the last 3 commits", "this branch vs main"), use that.

For each of the 22 flags, mark exactly one of:

- **PASS** — flag does not apply
- **N/A** — flag is structurally irrelevant to this change (e.g. no functions added → pass-through-method N/A)
- **FIXED** — flag applied; you fixed it during this review
- **JUSTIFIED** — flag applies but the design choice is deliberate; explain in one line

### Ousterhout (13)

1. Shallow module — interface as complex as implementation?
2. Information leakage — same decision in two places?
3. Temporal decomposition — modules organised by execution order?
4. Overexposure — users forced to know internals?
5. Pass-through method — function only forwards arguments?
6. Repetition — similar patterns in multiple places?
7. Special-general mixture — special-case logic tangled with general?
8. Conjoined methods — A only readable by reading B?
9. Comment repeats code — comment adds no information?
10. Implementation contaminates interface — API leaks internals?
11. Vague name — `data` `info` `manager` `helper` `util` `process` `handle`?
12. Hard to describe in a comment — abstraction is wrong?
13. Hard to pick a name — wrong unit?

### Pragmatic (5)

14. Broken window — rot you didn't fix or ticket?
15. Resource leak — open without `with` / try-finally / defer?
16. Silent failure — exception swallowed without log/re-raise?
17. Untested behaviour — code path no test exercises?
18. Premature abstraction — flexibility for an unnamed need?

### Karpathy (4)

19. Unstated assumption — guessed instead of asked?
20. Off-task change — line that doesn't trace to the request?
21. Speculative feature — added what wasn't asked?
22. Weak success criterion — can you state the verifying test?

End with a one-line summary: "X PASS · Y N/A · Z FIXED · W JUSTIFIED" and any FIXED items as a separate diff if they require code changes.
