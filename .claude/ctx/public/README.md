# Public memory

The only tracked path under `.claude/ctx/`. Everything else in this directory is
local operational memory and is gitignored — see
[ADR 0004](../../../docs/decisions/0004-ctxpack-memory-scopes.md).

## What belongs here

A deliberately authored, sanitized projection of context worth publishing: the
kind of thing a new contributor or a downstream consumer should be able to read.
It is written for them, not extracted from a transcript that happened to contain
it.

## What does not

- Raw session records (`*.ctx`), derived gists, checkpoint or event ledgers.
- Absolute paths naming anyone's home directory, machine or unrelated repository.
- Verbatim user prompts.
- Anything credential-shaped, ever.

Durable decisions belong in `docs/decisions/`, issues, or the specification —
artifacts with an audience and a review path. This directory is for context that
is genuinely CtxPack-shaped and genuinely public, and it is expected to stay
small. If a file here would be better as an ADR, make it an ADR.

## Enforcement

`harness/selfci/release_privacy.py` scans every path the release archive would
carry, including this one. Adding a file here that names a real home directory or
carries a credential-shaped string fails the blocking suite. The scanner's own
patterns are self-tested, because a privacy scanner that silently matches nothing
reports a clean tree and is indistinguishable from one.
