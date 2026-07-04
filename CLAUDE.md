
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
