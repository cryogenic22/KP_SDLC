# ADR 0004 — CtxPack memory scopes: local, team, public

**Status:** Proposed
**Date:** 2026-09-12
**Supersedes:** the `.gitignore` comment claiming "project settings + ctx ledger
are shared (committed)", which was a default rather than a decision.
**Related:** #39 (release blocker), #37 (release checklist), §10 of
`docs/specifications/agent-assurance-control-plane.md`

## Context

`.gitignore` un-ignored `.claude/ctx/` wholesale, so every CtxPack artifact the
session hooks wrote became tracked and would ship in the release archive. At
`db7294f` that meant publishing:

| Path | What it is |
|---|---|
| `.claude/ctx/session-ca35891c.ctx` | ~47 KB transcript-derived record — verbatim user prompts, tool commands, working context from other repositories |
| `.claude/ctx/session-ca35891c-gist.md` | derived session gist |
| `.claude/ctx/latest-gist.md` | copy of the above |
| `.claude/ctx/checkpoints.jsonl` | per-session checkpoint ledger |

A scan of all 328 tracked paths at `origin/main` found absolute user paths in
exactly three of them — 108, 7 and 7 hits — and in nothing else:

```console
$ python harness/selfci/release_privacy.py --rev origin/main
[release-privacy] 123 finding(s) across 4 file(s):
  .claude/ctx/checkpoints.jsonl          (1 hit: local-only-artifact)
  .claude/ctx/latest-gist.md             (7 hits: absolute-user-path, local-only-artifact)
  .claude/ctx/session-ca35891c-gist.md   (7 hits: absolute-user-path, local-only-artifact)
  .claude/ctx/session-ca35891c.ctx       (108 hits: absolute-user-path, local-only-artifact)
```

**No credential is asserted by this finding**, and none was found. The problem is
unclassified operational and personal context in a public product artifact.

The specification already named this: §10 records that `.gitignore` deliberately
un-ignores `.claude/ctx/`, calls the committed location with unsanitized content
the real gap, and makes closing it ACP-7's first task. This ADR closes the
release-boundary half now, because a release cannot wait for ACP-7.

## Decision

**Three scopes, with local as the default and public as opt-in.**

| Scope | Contents | Where it lives | Tracked |
|---|---|---|---|
| **local** | raw session records (`*.ctx`), derived gists, the checkpoint and event ledgers — everything the session hooks write by default | `.claude/ctx/` on the operator's machine | no |
| **team** | nothing yet. Reserved for a future sanitized share that is not a public release artifact; it needs a sanitizer and a review path before it can exist | — | no |
| **public** | a deliberately authored, sanitized projection of durable decisions | `.claude/ctx/public/` | yes |

Four rules follow:

1. **Raw session memory is never tracked.** `.gitignore` ignores `.claude/ctx/*`
   and un-ignores only `.claude/ctx/public/`. A new session cannot reach a
   release archive by default — which is the property the previous blanket
   un-ignore lacked, since every new `.ctx` file became tracked-by-default the
   moment it was written.

2. **Nothing is deleted from the operator's disk.** The four tracked files are
   removed with `git rm --cached`, so the owner's ledger is intact and CtxPack
   recall keeps working exactly as before. Only the *tree* changes.

3. **Durable decisions live in ADRs, issues and the specification** — artifacts
   that are written to be read by someone else — not in raw transcripts that
   happen to be readable. Where a raw record holds something worth keeping, it is
   restated deliberately rather than published wholesale.

4. **History is not rewritten here.** The blobs remain reachable in existing
   history. Since no credential is involved, rewriting shared history to hide
   non-secret path metadata would cost every clone and buy little; #39 states the
   same. If a credential is ever found, the order is rotate first, then treat the
   rewrite as its own coordinated operation.

## Enforcement

`harness/selfci/release_privacy.py` scans the exact file set `git archive` would
emit, reading blob content from git rather than the working tree. It flags three
classes: credential-shaped strings, absolute user paths with a real username
(placeholders like `<user>` and `/home/runner/` are allowed), and local-only path
shapes. It runs in the blocking suite.

**The detector carries its own positive control.** While investigating #39 a scan
reported a clean tree because its own regex was wrong: a shell-escaped
`C:\\Users\\` reached grep as `C:\Users\`, where `\U` silently degraded to a
literal and the pattern matched nothing. The absence of findings was
indistinguishable from safety. `selftest()` therefore asserts every rule matches
a known positive and rejects a known negative, and it runs before any scan result
is trusted — a scanner that cannot fail manufactures confidence.

## Consequences

- The release archive carries product source and a sanitized public projection,
  nothing else.
- Cross-session recall is unaffected: CtxPack reads `.claude/ctx/` from disk, and
  Observatory's `health.py` and `memory.py` do the same. No test depended on
  those files being tracked.
- A contributor who wants a decision to outlive their machine must write it down
  somewhere a reader will find it. That is a cost, and it is the right one.
- ACP-7 still owns the larger CtxPack sanitization contract. This decision fixes
  the release boundary and does not pre-empt it.

## Alternatives rejected

- **Sanitize the tracked records in place.** Rewriting 47 KB of transcript to
  scrub paths leaves verbatim prompts and cross-repository context, which is the
  larger half of the problem. Sanitization without a schema is a filter someone
  has to keep ahead of.
- **Track everything and scrub at release time.** The scrubber becomes the only
  thing standing between a routine session and a publication, and it is exactly
  the component that failed silently above.
- **Rewrite history now.** Disproportionate with no credential involved, and it
  invalidates every existing clone. Kept available as a separate decision.
