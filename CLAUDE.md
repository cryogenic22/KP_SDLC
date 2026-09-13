# KP_SDLC Agent Instructions

KP_SDLC is an assurance harness for agentic software delivery. These rules bind
implementation agents and reviewers working in this repository.

<!-- kp-sdlc:common-agent-contract:v1 -->
## Operating Contract

- Implementation agents may investigate, edit, test, commit, and open pull
  requests. They do not merge their own work.
- The designated independent reviewer owns the merge decision. Author
  self-review and author-run adversarial agents are evidence, not approval.
- Review the immutable remote head in an isolated worktree. Recheck the head
  before push or merge, use force-with-lease for rebases, and merge only the
  exact SHA that received fresh required checks.
- Never modify or discard another worktree's uncommitted changes. Use a clean
  worktree for release evidence.

## Engineering Standard

- Search before writing and prefer existing contracts, parsers, and component
  boundaries. New abstraction requires demonstrated reuse or reduced risk.
- A green result must prove that work executed. Every blocking gate needs a
  positive control, a planted failing case, and a non-zero execution count or
  an equivalent non-vacuous invariant.
- Bind merge and release evidence to the full commit SHA plus policy and config
  identity. Stale, malformed, missing, or self-reported evidence cannot become
  an independent pass.
- Deliver one useful end-to-end slice per PR. Defer fleet, signing, UI, and
  speculative project-shape machinery until a real pilot creates demand.
- Prefer deterministic checks for blocking decisions. Model review may surface
  candidates, but it cannot silently waive, weaken, approve, or merge.

## Review Convergence And Learning

- Before handoff, authors state change risk, protected invariants, applicable
  `KP-RV-*` patterns, and negative proof. A reviewer completes the full
  assurance sweep before publishing consolidated findings.
- Classify findings as `KNOWN`, `ESCAPED`, `NOVEL`, or `FALSE-POSITIVE`.
  Reproduce a novel issue before adding it to the review-convergence catalog;
  every known escape gets an explicit earliest-prevention action. Close each
  review with the `/close-review-loop` record.
- Optimize for fewer avoidable review rounds, never for approval rate. New
  evidence may stop a merge; nits and unrelated future work do not reopen a
  closed review area.
- The harness may propose learning changes, but only an independently reviewed
  PR may alter a catalog entry, gate, threshold, waiver, or merge decision.

## Context And Memory

- At session start or after compaction, read current Git state, this contract,
  and `.claude/ctx/latest-gist.md` when present. Use CtxPack ledger recall for
  older detail when available.
- Treat recalled summaries as leads, not authority. Verify mutable repository,
  PR, CI, and policy state at the current SHA before acting.
<!-- /kp-sdlc:common-agent-contract:v1 -->

<!-- ctxpack:session-memory:v1 -->
## Session memory (ctxpack ledger)

This repo uses CtxPack Checkpoint: hooks pack every compaction and
session end into `.claude/ctx/` (a deterministic ledger — the raw
transcript is never deleted), and each session start re-injects the
previous session's gist. Trust the gist's constraints and decisions.

**Recall past-session detail via the ledger read path FIRST**; fall back
to grepping the raw transcript only if it fails (fallbacks are tracked):

- MCP (if connected): `ctx/session_recall`, `ctx/session_timeline`,
  `ctx/session_decisions`, `ctx/why`, `ctx/graph_query`
- CLI twins: `ctxpack session decisions | timeline | recall | why | graph`
  (`--session <id>` targets older sessions; `ctxpack session stats` shows
  adoption + capture metrics)

**Decision convention (load-bearing):** state every nontrivial decision
(design choice, root cause, chosen fix, abandoned approach) in your reply
on its own sentence starting with `Decision:` — e.g. `Decision: use
exponential backoff with base 750ms because the vendor limit is 40
req/min.` The deterministic parser extracts these; unmarked decisions in
free prose are often missed. Dead ends the same way: "The X approach
didn't work because ...".
<!-- /ctxpack:session-memory -->
