# Structural Floor

The anti-tamper mechanism: **you can't quietly lower your own bar.**

When a gate is hard, the cheap move is to edit the gate. The Structural Floor
closes that loophole by coupling three things so the success-definition surface
lives in one place, mechanically generates the ownership rules, and a test proves
the two never drift:

```
protected-surface.txt   →   .github/CODEOWNERS   →   branch protection
  (source of truth)          (generated)              (enforces review)
        └──────────── sync test / CI gate proves no drift ────────────┘
```

- **`protected-surface.txt`** — the single source of truth. Every gate, threshold,
  config, and eval gold set that defines "success" is listed here, each owned by a
  reviewer (or a `# default-owner:`).
- **`gen_codeowners.py`** — renders `.github/CODEOWNERS` from the surface, and
  `--check` verifies they match (exit 1 on drift).
- **`test_protected_surface_sync.py`** + the **`structural-floor` CI workflow** —
  fail the build if `protected-surface.txt` and `.github/CODEOWNERS` ever diverge.

Coupled by design: adding a new hard gate means adding its path to
`protected-surface.txt` **and** regenerating CODEOWNERS in the same change — a
builder can't relocate the Goodhart point.

> **⚠️ Load-bearing assumption.** The actual *blocking* lives in GitHub branch
> protection — "require review from Code Owners" + "disallow self-approval" — which
> is **server-side config, not in the repo**. This control keeps `CODEOWNERS`
> honest (it can't be silently weakened without a CI failure), but a repo admin can
> still disable code-owner enforcement with zero repo diff and zero CI signal.
> Treat the branch-protection setting as the single point of failure: lock it down
> and audit it out-of-band. Everything else here only has teeth because of it.

## Files

| File | Role |
|---|---|
| `gen_codeowners.py` | Generator + `--check` drift detector (stdlib only) |
| `protected-surface.txt.tmpl` | Starter surface (substitute `{{OWNER}}` / `{{PROJECT_NAME}}`) |
| `test_protected_surface_sync.py.tmpl` | Sync test for the target project |
| `tests/` | Unit tests for the generator + KP_SDLC's own dogfood sync test |

## Bootstrap (into a target project)

`harness/bootstrap.sh` installs:

```
scripts/gen_codeowners.py
protected-surface.txt                      # from the .tmpl
tests/test_protected_surface_sync.py       # from the .tmpl
.github/workflows/structural-floor.yml     # from harness/ci/
```

Then:

1. Replace `{{OWNER}}` in `protected-surface.txt` with your reviewing owner/team,
   and list the paths that define success.
2. `python scripts/gen_codeowners.py` → writes `.github/CODEOWNERS`.
3. Commit `protected-surface.txt` **and** `.github/CODEOWNERS` together.
4. In GitHub branch protection for `main`: require a pull request, require review
   from Code Owners, and disallow self-approval. Now a change to any protected
   path needs the owner — and the CI gate blocks any CODEOWNERS hand-edit.

## Usage

```bash
python scripts/gen_codeowners.py            # write .github/CODEOWNERS
python scripts/gen_codeowners.py --check    # exit 1 if stale (CI / pre-commit)
python scripts/gen_codeowners.py --root .   # explicit repo root
```

## protected-surface.txt format

```
# default-owner: @your-org/leads

path/to/a/gate.config            # uses the default owner
path/to/another @specific-owner  # explicit owner overrides the default
.github/workflows/               # directory protection (gitignore-style)
```

Blank lines and `#` comments are ignored (except the `# default-owner:` directive).
A protected path with no owner and no default is a hard error — an unenforceable
protection is never silently emitted (no vacuous green).
