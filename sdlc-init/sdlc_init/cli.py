"""`sdlc init` — the born-gated front door.

One command turns an empty directory into a repo that is gated from birth:
harness installed, placeholders filled, config-carrying workflows parked,
structural floor generated and proven in sync, engine pinned by SHA in a
manifest. The `bootstrap` subcommand is the copy-only path the thin
bootstrap.sh shim calls (backward compatibility, single source).
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import harness_map as hm
from . import phases as ph
from .executor import InitContext, run
from .manifest import InitManifest


def _default_engine_root() -> Path:
    # sdlc-init/sdlc_init/cli.py → engine root is two parents up.
    return Path(__file__).resolve().parents[2]


def _today() -> str:
    return datetime.date.today().isoformat()


def _prompt(label: str, current: str | None) -> str:
    if current:
        return current
    if not sys.stdin.isatty():
        raise SystemExit(f"error: --{label} is required in non-interactive mode")
    try:
        return input(f"{label}: ").strip()
    except EOFError:  # piped/closed stdin — treat as non-interactive
        raise SystemExit(f"error: --{label} is required (no input available)")


def _make_context(args, *, dry_run: bool, subs_name: str, subs_owner: str) -> InitContext:
    engine_root = Path(args.engine_root).resolve()
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    manifest = InitManifest(
        project_name=subs_name or "",
        owner=subs_owner or "",
        target=target,
        engine_root=engine_root,
        profile=getattr(args, "profile", "explore"),
    )
    manifest.validate()
    as_of = args.as_of or _today()
    return InitContext(
        manifest=manifest,
        harness_dir=engine_root / "harness",
        as_of=as_of,
        subs=hm.substitutions(project_name=subs_name, owner=subs_owner, as_of=as_of),
        dry_run=dry_run,
        log=print,
    )


def _preflight_conflicts(target: Path) -> list[str]:
    """Gating files init would generate/own that already exist as user content.
    A repo init already created (carries our manifest) is exempt — re-running
    is idempotent by design."""
    if (target / ".harness" / "manifest.json").exists():
        return []
    conflicts = [f for f in hm.GATING_FILES if (target / f).exists()]
    wf_dir = target / hm.WORKFLOWS_DEST
    if wf_dir.is_dir():
        conflicts += [f"{hm.WORKFLOWS_DEST}/{p.name}" for p in sorted(wf_dir.glob("*.yml"))]
    return conflicts


def cmd_init(args) -> int:
    name = _prompt("name", args.name)
    owner = _prompt("owner", args.owner)
    ctx = _make_context(args, dry_run=args.dry_run, subs_name=name, subs_owner=owner)
    conflicts = _preflight_conflicts(ctx.target)
    if conflicts:
        print(f"[sdlc init] refusing: target already has gating files: "
              f"{', '.join(conflicts)}", file=sys.stderr)
        print("[sdlc init] init creates a repo from birth. Init into an empty "
              "directory, or use `sdlc bootstrap` to layer the harness into an "
              "existing repo (it never overwrites).", file=sys.stderr)
        return 2
    print(f"[sdlc init] {name}  owner={owner}  target={ctx.target}"
          + ("  (dry-run)" if args.dry_run else ""))
    run(ctx, [ph.copy_harness, ph.park_readme, ph.vendor_engine, ph.setup_floor,
              ph.born_gated_proof, ph.write_manifest])
    failed = [r for r in ctx.results if r.status == "fail"]
    if failed:
        print(f"[sdlc init] FAILED: {', '.join(r.name for r in failed)}", file=sys.stderr)
        return 1
    if args.dry_run:
        print("[sdlc init] dry-run complete — nothing written.")
        return 0
    print(f"[sdlc init] done. Next: cd {ctx.target}, commit, then push and enable "
          f"branch protection so CODEOWNERS is enforced.")
    return 0


def cmd_bootstrap(args) -> int:
    """Copy-only path (bootstrap.sh shim). Leaves {{PROJECT_NAME}}/{{OWNER}} for
    manual fill, matching legacy bootstrap behavior — but still parks config
    workflows and ships .gitignore (strict improvements)."""
    ctx = _make_context(args, dry_run=args.dry_run,
                        subs_name="{{PROJECT_NAME}}", subs_owner="{{OWNER}}")
    print(f"[sdlc bootstrap] target={ctx.target}")
    run(ctx, [ph.copy_harness, ph.park_readme])
    print("[sdlc bootstrap] done. Fill {{PROJECT_NAME}}/{{OWNER}}, or use `sdlc init` "
          "to do it end-to-end.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdlc", description="Born-gated repo setup")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create a born-gated repo end-to-end")
    p_init.add_argument("--name", help="Project name (fills {{PROJECT_NAME}})")
    p_init.add_argument("--owner", help="Reviewing owner, e.g. @user or @org/team")
    p_init.add_argument("--target", default=".", help="Target repo dir (default: cwd)")
    p_init.add_argument("--profile", default="explore", help="Init profile (default: explore)")
    p_init.add_argument("--engine-root", default=str(_default_engine_root()),
                        help="KP_SDLC engine checkout (default: this repo)")
    p_init.add_argument("--as-of", default=None, help="ISO date stamp (default: today)")
    p_init.add_argument("--dry-run", action="store_true", help="Plan only; write nothing")
    p_init.set_defaults(func=cmd_init)

    p_bs = sub.add_parser("bootstrap", help="Copy-only harness install (shim path)")
    p_bs.add_argument("--target", default=".", help="Target repo dir (default: cwd)")
    p_bs.add_argument("--engine-root", default=str(_default_engine_root()))
    p_bs.add_argument("--as-of", default=None)
    p_bs.add_argument("--dry-run", action="store_true")
    p_bs.set_defaults(func=cmd_bootstrap)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
