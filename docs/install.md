# Installing KP_SDLC and creating a born-gated repository

The supported path is a normal Python install of the `kp-sdlc` distribution,
followed by `sdlc init` run from the directory where you want the new repository.
No checkout of this repository is required.

## Install

```bash
python -m venv .venv
.venv/bin/pip install kp-sdlc            # Windows: .venv\Scripts\pip install kp-sdlc
```

Runtime dependencies are deliberately empty. `[dev]` adds PyYAML and pytest and
is only needed to run this repository's own test corpus.

The install provides these console entry points: `sdlc`, `qg`, `ck`,
`sdlc-schemas`, `rv`, `ee`, `g1`, `g2`, `kp-observatory`.

## Create a born-gated repository

```bash
sdlc init --name MyProject --owner @me --target ../my-project
```

`init` refuses to run over an existing repository that already carries
`CLAUDE.md`, `AGENTS.md`, `protected-surface.txt`, `.github/CODEOWNERS` or
`.quality-gate.json`, because those are files it generates and owns. To layer
the harness into a repository that already exists, use the copy-only path:

```bash
sdlc bootstrap --target .
```

## Where the engine assets come from

`init` and `bootstrap` read two things from an *engine root*: the harness tree
they install, and the Quality Gate / Cathedral Keeper sources they vendor into
the new repository's `tools/qa/`.

An installed distribution carries both as a **packaged payload** inside
`sdlc_init/_payload`, staged at build time by `build_support/kp_build_backend.py`.
Resolution order is:

1. an explicit `--engine-root`;
2. the packaged payload, when running from an install;
3. the surrounding source checkout, when running from a clone.

If none of those resolves, or the resolved root is missing any required asset,
the command exits non-zero and names what is missing **before writing anything
into the target**. It does not partially provision and leave you to find out
later.

You only need `--engine-root` to pin a new repository to a specific checkout of
this engine rather than to the version you installed.

## What the manifest records

Every generated repository gets `.harness/manifest.json`, recording which engine
gated it at birth. The `engine.provenance` block distinguishes the two cases:

```jsonc
// installed from a release artifact
"provenance": { "kind": "package",
                "package_version": "0.6.0",
                "payload_digest": "sha256:…" },
"sha": null

// run from a source checkout
"provenance": { "kind": "checkout", "package_version": "…" },
"sha": "40-hex commit"
```

A packaged install records `sha: null` on purpose. It has no commit of its own,
and `git rev-parse` run from inside `site-packages` can succeed by walking up
into whatever repository happens to contain the environment — so a release
artifact would otherwise report a commit it was never built from. Its identity
is the distribution version plus the payload digest.

`sdlc status` reads this manifest to report drift between the vendored engine in
a born repository and the engine it was pinned to.

## Verifying an install yourself

```bash
python harness/selfci/artifact_smoke.py
```

Builds a wheel, installs it into a throwaway virtualenv, runs `sdlc init` and
`sdlc bootstrap` from outside the checkout, checks the generated repository is
genuinely gated, then deletes one required payload asset and requires the next
run to fail and name it. The same driver runs in this repository's blocking test
suite (`harness/selfci/tests/test_artifact_smoke.py`).
