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

## Context And Memory

- At session start or after compaction, read current Git state, this contract,
  and `.claude/ctx/latest-gist.md` when present. Use CtxPack ledger recall for
  older detail when available.
- Treat recalled summaries as leads, not authority. Verify mutable repository,
  PR, CI, and policy state at the current SHA before acting.
<!-- /kp-sdlc:common-agent-contract:v1 -->

