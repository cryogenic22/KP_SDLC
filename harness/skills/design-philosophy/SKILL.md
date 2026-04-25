---
name: design-philosophy
description: Apply when writing, reviewing, or refactoring code. Tier 0 entropy framing + Tier 1 always-on principles synthesised from Karpathy, Ousterhout's "A Philosophy of Software Design", Hunt & Thomas's "The Pragmatic Programmer", and software-entropy theory. Tier 2 red-flag self-review for pre-commit.
sources:
  - Andrej Karpathy — coding heuristics (via forrestchang/andrej-karpathy-skills, MIT)
  - John Ousterhout — "A Philosophy of Software Design", 2nd ed. (Yaknyam Press, 2021)
  - Andrew Hunt & David Thomas — "The Pragmatic Programmer", 20th anniversary ed. (Addison-Wesley, 2019)
  - Software-entropy / "broken-window theory" — Wilson & Kelling (1982), applied to software by Hunt & Thomas
license: MIT
source: kp-sdlc/harness
---

# Design philosophy

Four sources, one coherent system. The four agree more than they disagree — this skill makes that agreement explicit and applicable at every commit.

## Tier 0 — The meta-principle: entropy

> Every change either fights entropy or feeds it. Default is feeding. Choose.

Codebases drift toward incoherence unless an active force pushes the other way. The principles below are the active force. They aren't rules to follow for their own sake — they are the *means*; preventing entropy is the *end*.

**Operationally:** ask before every commit — *am I leaving a broken window?* If yes, fix it now or open an explicit ticket. Never let rot stand unannotated.

---

## Tier 1 — Always-on principles

These read every session. They drive judgment during planning and writing. Not all apply to every change — pick the ones that do.

### Design (from Ousterhout)

1. **Deep modules, not shallow.** Powerful interface, simple API; complexity hidden inside. A class with three methods that solve a hard problem is deeper than a class with thirty methods that just delegate.
2. **Information hiding (no leakage).** Each module hides its design decisions. If the same decision must be implemented in two places, that's information leakage — the abstraction is wrong.
3. **Pull complexity downward.** Module authors should bear the pain so users don't. Default arguments, sensible behaviour, errors-handled-internally.
4. **Define errors out of existence.** Don't return more errors than necessary. Zero error paths is best (e.g., string operations that handle empty strings instead of returning null).
5. **Different layer, different abstraction.** A function that just forwards arguments to another function (a "pass-through") doesn't change abstraction — it adds nothing but a name.

### Process (from Pragmatic Programmer)

6. **Don't live with broken windows.** Triage the moment you see rot — fix it, board it up explicitly with a ticket, or accept it as a deliberate decision. Never let it sit silently.
7. **Tracer bullets, not waterfalls.** Build end-to-end thin slice, then thicken. Validates the architecture early; gives every contributor a working system to extend.
8. **Reversibility — preserve options.** Defer irreversible decisions. Keep architecture flexible. "Deferred, not deleted" is a legitimate state.
9. **Crash early.** When a real error truly occurs, fail loudly and fast. Better than drifting in inconsistent state. (Note the contrast with Ousterhout's #4: define errors out where you can; when one is genuine, don't hide it.)
10. **DRY.** Every piece of knowledge has one unambiguous representation. Reinforces #2 (information hiding) from a different angle.
11. **Good enough software.** Avoid gold-plating. Trade quality for time deliberately, not by accident. The rule-set itself can become entropy if applied dogmatically.

### Discipline (from Karpathy)

12. **Think before coding.** State assumptions. Surface ambiguity. Ask before guessing.
13. **Simplicity first.** Minimum code that solves the problem. No speculative flexibility.
14. **Surgical changes.** Touch only what the task requires. Clean only your own mess.
15. **Goal-driven execution.** Define verifiable success criteria. Loop until checked.

### Cross-cutting

16. **Design twice.** When facing a non-trivial design choice, sketch two approaches before committing. Cheap; catches dead-ends early.
17. **Refactor mercilessly when you smell something.** Small fixes prevent big debt. Pairs with #6 (broken windows).
18. **Design by contract.** Make pre-conditions, post-conditions, and invariants explicit — via types, asserts, or schemas. mypy-strict + Pydantic + TS-strict are most of this for free.
19. **Test ruthlessly.** "If it isn't tested, it's broken." Every new behaviour has a test before it commits.
20. **Code is read 10× more than written.** Optimise for the reader. Clarity beats cleverness.

---

## Tier 2 — Red-flag self-review (run before every commit)

Walk this checklist before you `git commit`. Each item is a flag — if it applies, either fix it now or document why it doesn't.

### Ousterhout's design red flags (13)

| # | Flag | Quick test |
|---|---|---|
| 1 | **Shallow module** | Is the interface as complex as the implementation? |
| 2 | **Information leakage** | Did you implement the same decision in two places? |
| 3 | **Temporal decomposition** | Are modules organised by execution order rather than abstraction? |
| 4 | **Overexposure** | Are users forced to know internals to use the API? |
| 5 | **Pass-through method** | Does the function do nothing but forward arguments? |
| 6 | **Repetition** | Are similar code patterns appearing in multiple places? |
| 7 | **Special-general mixture** | Is special-case logic tangled with general logic? |
| 8 | **Conjoined methods** | Can A only be understood by reading B? |
| 9 | **Comment repeats code** | Does the comment add information beyond what the code says? |
| 10 | **Implementation contaminates interface** | Does the API surface internal structure? |
| 11 | **Vague name** | Does the identifier use `data`, `info`, `manager`, `helper`, `util`, `process`, `handle`? |
| 12 | **Hard to describe in a comment** | If the docstring is awkward, the abstraction is wrong. |
| 13 | **Hard to pick a name** | If naming is hard, you have the wrong unit. |

### Pragmatic checklist (5)

| # | Flag | Quick test |
|---|---|---|
| 14 | **Broken window** | Did you spot rot you didn't fix or ticket? |
| 15 | **Resource leak** | Did you open a file/connection/lock without `with` / try-finally / defer? |
| 16 | **Silent failure** | Did you swallow an exception without logging or re-raising? |
| 17 | **Untested behaviour** | Did you add a code path no test exercises? |
| 18 | **Premature abstraction** | Did you add flexibility for a need you can't name? |

### Karpathy checklist (4)

| # | Flag | Quick test |
|---|---|---|
| 19 | **Unstated assumption** | Did you guess instead of asking? |
| 20 | **Off-task change** | Does any line not trace to the user's request? |
| 21 | **Speculative feature** | Did you add what wasn't asked for? |
| 22 | **Weak success criterion** | Could you state the test that proves the change correct? |

### Use

This checklist is invoked by:
- The `/review` slash command (manual)
- The `/before-i-commit` slash command (manual, pre-commit)
- The pre-commit `red-flag-attestation` hook (automated; appends a `### Self-review` section to the commit body)
- The `second-pass-reviewer` CI workflow (independent fresh-context Claude session reviews the diff against this list)

---

## What this skill is NOT

- **Not a linter.** Mechanical rules live in `quality-gate/` (PRS scoring) and `cathedral-keeper/` (architecture). This skill is the judgment layer.
- **Not exhaustive.** Each source has principles we deliberately do not encode (Karpathy's "knowledge portfolio", Pragmatic's editor-power tips, Ousterhout's chapter on design-it-twice as a process). Add only when a real failure motivates encoding.
- **Not immutable.** When a principle stops earning its keep, retire it via the rule-audit log. The system is self-correcting, not dogmatic.

## How to apply

- During planning: read Tier 1 once. Decide which 3-5 principles bear on this change.
- During writing: keep the relevant subset top-of-mind. Don't fight the others.
- Before commit: walk Tier 2. Mark each as PASS or justify.
- During code review: use the checklist as the diff lens.
- Quarterly: audit what flagged often, what never flagged. Retire dead weight, add what you keep manually catching.
