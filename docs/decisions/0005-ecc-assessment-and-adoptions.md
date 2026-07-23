# 0005 — Assessing ECC; adopting three ideas in-doctrine

**Status:** Accepted (assessment + adoption decisions). The flagship adoption
(harness-surface audit) is scoped here as a candidate loop, not yet built.

## Context

We were asked whether [ECC](https://github.com/affaan-m/ecc) — "the agent harness
performance optimization system" — could be an upgrade to this harness. ECC is a
breadth-first, plugin-distributed harness OS for Claude Code and ~6 other
harnesses: ~278 skills, ~67 agents, ~34 rule sets, 15+ Node hooks, an LLM-based
continuous-learning system, and a security scanner (AgentShield). Node/TS +
Python, MIT OSS with a paid Pro tier, installed globally into `~/.claude/`.

(ECC figures here are self-reported from its README, read via a summarizing
fetch — treat them as claims, not an audited count. The architectural
observations below do not depend on the exact numbers.)

## The finding: opposite doctrines

ECC and this system are built on contradictory theses, which is the whole answer
to "is it an upgrade":

| Axis | ECC | KP_SDLC (this repo) |
|---|---|---|
| Unit of install | Global `~/.claude/`, copied config | **Born-gated per-repo, SHA-pinned vendored engines + manifest** |
| Determinism | LLM-driven, confidence-scored, probabilistic | **Deterministic, fail-closed, anti-vacuous** |
| Dependencies | Node/TS + Prettier/tsc/external tools | **Zero-dependency stdlib doctrine** |
| Surface strategy | Maximize (skills/agents/rules) | Minimize surface, gate everything |
| Trust model | Third-party Node hooks on every tool call, global | Vendored, hash-pinned bytes per repo (`sdlc status`, PR #28) |
| Improvement loop | LLM mines instincts → confidence → evolve to skill | **Measure before mining; deterministic detectors; human-gated apply** (ADR 0004) |

## Decision

**Do not adopt ECC as a platform.** Wholesale adoption would fight the grain of
the born-gated / deterministic / zero-dep design and dilute it. Instead, adopt
three of its *ideas*, each reworked to this repo's philosophy. The filter for
"net positive with us" is explicit: an idea qualifies only if it can be made
**deterministic, fail-closed, zero-dependency, and per-repo** — otherwise it is
noted and rejected, not imported.

### Adoption 1 (flagship) — a harness-surface audit gate

**ECC idea:** AgentShield scans ECC's *own* hooks, configs, skills, MCP and
permissions for vulnerabilities — governance turned on the harness itself.

**Why it is net-positive here:** this repo gates *product* code with Quality Gate
and *architecture* with Cathedral Keeper, but **nothing gates the harness's own
executable surfaces.** Concretely, in this repo those surfaces are:

- `.claude/settings.json` — 12 hook events wiring three distinct programs
  (`harness/hooks/reuse_injector.py`, `observatory/claude_hook.py`,
  `ctxpack.cli.main`), each auto-executed on tool events.
- `harness/templates/claude-settings.json.tmpl` — what ships to born repos: one
  auto-executed `PreToolUse` hook, `python -P .harness/hooks/reuse_injector.py`.
- `harness/hooks/*` (`reuse_injector.py`, `second_pass_reviewer.py`,
  `red-flag-attestation.sh`, `pre-commit-config.yaml.tmpl`).
- `harness/skills/*/SKILL.md`, the shipped MCP config, and the FILE_MAP that
  fans all of this into a born repo.

A born repo runs whatever hooks it was born with, forever, and nothing checks
that those hook commands are well-formed, that they reference files that exist
and match the manifest hash, or that no unpinned/unknown program was wired in.
That is the same blind spot `sdlc status` (PR #28) just closed for engine
*bytes*, one layer up — from "are my vendored engine files intact?" to "are my
auto-executed harness surfaces safe and pinned?"

**Reworked to doctrine** (this is the actual adoption, not AgentShield's code):

- **Deterministic checks, not an LLM.** A fixed rule set over the hook/config/
  skill surface — no model in the gate path.
- **Zero-dependency**, stdlib only, emitting the shared finding shape
  `{rule, severity, file, line, message}` so it composes with QG/CK reporting.
- **Fail-closed**: a surface it cannot parse is a finding, never a silent pass
  (mirrors QG's vacuity posture).
- **Manifest-aware**: a hook command that references a file absent from — or
  hash-mismatched against — `.harness/manifest.json` is drift, reusing the
  `engine.vendored` record `sdlc status` already reads.
- **Per-repo / born-gated**: ships in the born-repo gate set so every born repo
  audits its own harness surface, not just this engine repo.

Scoped as a candidate loop in the appendix below.

### Adoption 2 — hook strictness profiles

**ECC idea:** `ECC_HOOK_PROFILE=minimal|standard|strict` and
`ECC_DISABLED_HOOKS=...` tune hook behavior at runtime via environment variables,
no code edits.

**Why it is net-positive here:** we already have the one-off precedent
(`OBSERVATORY_DISABLE=1`, `OBSERVATORY_CAPTURE_INPUTS=1`). A single profile knob
across all harness hooks is a clean ergonomic and directly serves the
generalized, brand-neutral, modular framing this toolkit aims for.

**Reworked to doctrine:**

- **Fail-open, always.** A profile or disable flag may only *reduce* what runs; a
  malformed value falls back to the standard profile and never breaks a session.
  (Hooks are already required to fail-open — this preserves that.)
- **Deterministic and documented**: the profile→enabled-hooks mapping is an
  explicit table, testable, with an anti-case proving a disabled hook does not
  fire and a malformed value does not escalate strictness.
- Small, low-conflict; a candidate for a later standalone PR, not urgent.

### Adoption 3 — the learning system as a design foil, not a component

**ECC idea:** continuous-learning-v2 mines session patterns with an LLM,
confidence-scores them (0–1, threshold 0.7), TTL-prunes pending ones, and
`/evolve` clusters instincts into skills.

**Why it matters here:** this is *exactly* the self-healing flywheel's Loops 2–3
(ADR 0004) — already shipped, the other way. Its value to us is as calibration,
not code:

- It **validates the direction**: pattern-mining → scored proposal → graduation
  to a reusable artifact is a real, shipped shape.
- It **demonstrates the failure mode we already designed against**: LLM-as-sole-
  extractor is the "marking your own homework" circularity ADR 0004 bans. ECC is
  the live cautionary case for why Loop 2 uses deterministic detectors and Loop 4
  freezes a blind-labeled corpus *before* proposals exist.
- Two of its primitives are worth borrowing into Loop 3's proposal record:
  **confidence scoring** and **TTL/pruning of unconfirmed candidates**. Adopt the
  primitives; keep the extractor deterministic.

**No code import.** This is guidance folded into Loops 2–4, not a subsystem.

## What we explicitly reject, and why

- **Global `~/.claude/` install** — contradicts born-gated, per-repo pinning.
- **Node/TS runtime + external tool deps** — contradicts the zero-dep doctrine;
  every adopted idea above is achievable in stdlib Python.
- **Probabilistic instinct injection into the live loop** — contradicts
  deterministic/fail-closed; and unreviewed auto-injected guidance is the
  circularity hazard.
- **278-skill / 67-agent breadth + plugin distribution** — contradicts
  minimize-surface; breadth is a maintenance liability here, not an asset.
- **Third-party hooks executed globally on every tool call** — the opposite of
  vendoring hash-verified bytes; it is precisely the trust surface Adoption 1
  exists to *audit*.

## Consequences

- One concrete, in-doctrine gap identified and scoped (Adoption 1). It slots
  beside QG/CK as a governance gate and reuses the manifest `sdlc status`
  already produces — high fit, low new surface.
- Two smaller, deferred wins (profiles; learning primitives) recorded so they are
  not re-derived.
- A durable record of *why* a superficially attractive, mature, popular system is
  not the upgrade — so the next person who finds ECC does not re-run this
  analysis from zero.

Deferred honestly: ECC's **cross-harness adapter** pattern (one harness OS across
7 tools) is genuinely interesting and aligns with the modular framing, but it is
a large lift with no current pull. Noted, not scheduled.

---

## Appendix — candidate loop: harness-surface audit gate

Not one of ADR 0004's eight flywheel loops (those are the measure→mine→apply
cycle). This is a **governance gate**, a sibling to QG and CK, and can be built
independently of the flywheel.

### Problem

Harness surfaces that auto-execute (hooks) or steer the agent (skills, configs,
MCP) are ungated. A born repo cannot tell that its wired hook commands are
well-formed, reference files that exist and match the manifest, or that no
unknown program was introduced. Product code is gated; the harness that produces
it is not.

### What it scans (grounded in this repo's real surfaces)

1. `.claude/settings.json` and `harness/templates/claude-settings.json.tmpl` —
   every hook command.
2. `harness/hooks/*` and the FILE_MAP entries that ship them.
3. `harness/skills/*/SKILL.md` and the shipped MCP config.

### Checks (deterministic, fail-closed)

- **HS-HOOK-RESOLVABLE** — every hook command references a program that exists in
  the tree. A dangling reference is a finding, not a runtime surprise.
- **HS-HOOK-PINNED** — a hook command pointing at a vendored/manifest-tracked file
  whose hash does not match `.harness/manifest.json` is drift (reuses the
  `engine.vendored` record).
- **HS-HOOK-SHELL-SAFETY** — flag hook command shapes that widen the trust
  surface (unpinned `curl … | sh`, absolute paths outside the repo, shell
  interpolation of untrusted input). A deterministic allow-shape list, not an LLM
  judgement.
- **HS-CONFIG-WELLFORMED** — settings/MCP JSON parses and matches the expected
  hook schema; an unparseable surface fails closed.
- **HS-SKILL-DECLARED** — shipped skills are the ones the manifest/FILE_MAP
  declares; an undeclared `SKILL.md` on the auto-loaded path is surfaced.

### Invariants

- **Deterministic** — no model in the gate path; identical inputs, identical
  findings.
- **Zero-dependency** — stdlib only; emits `{rule, severity, file, line, message}`.
- **Fail-closed** — an unparseable or unresolvable surface is a finding.
- **Anti-vacuous** — the pass path asserts a non-zero count of surfaces was
  actually inspected, so "0 findings" cannot mean "scanned nothing" (the exact
  vacuous-green trap that untracked/unscanned files caused before).
- **Born-gated** — ships in the born-repo gate set.

### Exit gate

Each check fires on a planted bad surface (a dangling hook reference; a
hash-mismatched pinned hook; a `curl | sh` shape; malformed settings JSON; an
undeclared skill) and stays silent on this repo's clean surfaces. The audit run
on this repo reports zero high findings.

### Non-goals

- No LLM. No auto-fix (findings only; any remediation goes through the existing
  human-gated `fix-engine` envelope later, if at all).
- No new runtime dependency, no global install, no product-code scope (that is
  QG/CK).

### Where it lives

A new check family emitting the shared finding shape, wired into the born-repo
gate set and this repo's `make check`, reusing the `.harness/manifest.json`
record `sdlc status` produces. Sits beside QG (code) and CK (architecture) as the
third governance axis: **the harness's own surfaces.**
