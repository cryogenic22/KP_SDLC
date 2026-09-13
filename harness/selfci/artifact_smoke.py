#!/usr/bin/env python3
"""Functional smoke against the *installed artifact*, not importable source.

Issue #38: a clean non-editable install succeeded and `sdlc init` then crashed
with "engine_root has no harness/ dir", because the wheel carried the Python
packages and none of the assets `copy_harness` and `vendor_engine` read. The
existing coverage was `-h` entry-point smoke, which a broken install passes, so
CI stayed green through a product that could not perform its primary function.

The fix for that class of miss is to stop testing the checkout. This driver:

  1. builds a wheel from a given source tree (through the in-tree backend, so
     the payload is staged exactly as a release would stage it);
  2. installs it non-editably into a throwaway venv with no dependencies;
  3. runs `sdlc init` and `sdlc bootstrap` **from a cwd outside the checkout**,
     with no `--engine-root`;
  4. asserts the born-gated repo is real — floor synced, manifest written, the
     vendored engine present — and that the manifest names its provenance as a
     package rather than inventing a git SHA;
  5. plants a failure: removes one required asset from the installed payload and
     requires the next run to exit non-zero and name it.

Step 5 is what makes steps 1-4 non-vacuous. Without it, a smoke that silently
stopped exercising the install would keep reporting success.

Usage:
    python harness/selfci/artifact_smoke.py [--source .] [--keep]

Exit codes: 0 all checks passed, 1 a check failed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Relative to the target repo. The set a born-gated repo must carry for the
# install to have done its job; a subset chosen to fail loudly rather than to
# restate sdlc-init's own tests.
BORN_ARTIFACTS = (
    "CLAUDE.md",
    "AGENTS.md",
    ".gitignore",
    ".harness/manifest.json",
    ".github/CODEOWNERS",
    "protected-surface.txt",
    "tools/qa/quality-gate/quality_gate.py",
    "tools/qa/cathedral-keeper/ck.py",
    ".claude/skills",
)

# The assets the planted-negative runs delete, and why there are two.
#
# The first is a template rather than a code file: it proves the check covers
# the harness payload, not just importable code that would fail on import
# anyway. On its own it was too weak. It is a FILE_MAP entry, so it is named
# individually in `required_assets()` and a plain `Path.exists()` finds it
# gone — which meant the planted failure shared the completeness check's blind
# spot and could not have detected it.
#
# The second sits *inside* a mapped directory. Nothing names it individually;
# the directory is the declaration. Deleting it left the directory present, so
# the old check reported a complete engine root and `sdlc init` went on to
# produce a repo silently missing a command.
PLANTED_VICTIM = "_payload/harness/templates/CLAUDE.md.tmpl"
PLANTED_NESTED_VICTIM = "_payload/harness/commands/review.md"


class SmokeFailure(RuntimeError):
    pass


def _run(argv: list[str], *, cwd: Path | None = None, env: dict | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        argv, cwd=None if cwd is None else str(cwd), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise SmokeFailure(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc


def _venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _exe(venv: Path, name: str) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    return str(_venv_bin(venv) / f"{name}{suffix}")


def build_sdist(source: Path, out_dir: Path, build_venv: Path) -> Path:
    """Build the sdist by calling the project's own PEP 517 backend.

    Invoked through the backend rather than `python -m build`, so the smoke
    needs no dependency the project does not already declare and what it
    exercises is the exact hook a release runs.

    Run inside a venv holding only the declared build requirement rather than
    in the ambient interpreter. That is not caution for its own sake: on the
    development machine a globally installed `pbr` hooks setuptools' egg_info
    entry points and raises `ModuleNotFoundError: pkg_resources` under Python
    3.13, which killed the build with nothing wrong in this repository. A smoke
    whose result depends on what else is installed cannot be evidence.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "-m", "venv", str(build_venv)])
    _run([_exe(build_venv, "python"), "-m", "pip", "install", "--quiet",
          "setuptools>=68.0"])
    # The output directory travels as argv rather than interpolated into the
    # source: it keeps Windows backslashes out of a Python literal, and it
    # keeps the engine's own `sql_string_interpolation` rule from reading
    # `sys.path.insert(...)` inside an f-string as a built SQL statement.
    stage_sdist = ("import sys; sys.path.insert(0, 'build_support');"
                   "import kp_build_backend as backend;"
                   "print(backend.build_sdist(sys.argv[1]))")
    _run([_exe(build_venv, "python"), "-c", stage_sdist, str(out_dir)],
         cwd=source)
    sdists = sorted(out_dir.glob("kp_sdlc-*.tar.gz"))
    if len(sdists) != 1:
        raise SmokeFailure(f"expected exactly one kp_sdlc sdist, found {sdists}")
    return sdists[0]


def build_wheel(source: Path, out_dir: Path) -> Path:
    """Build the wheel *from the sdist*, which is the path a release takes.

    Building in-tree hid two defects behind a checkout that simply had every
    file already: the sdist carried neither the in-tree build backend nor five
    of the eight sources `stage_payload()` reads, so `pip install` of the
    published artifact failed at "Cannot find module 'kp_build_backend'" before
    any code ran. An in-tree `pip wheel .` passes in both worlds, so it could
    never have caught it.
    """
    sdist = build_sdist(source, out_dir, out_dir.parent / "buildvenv")
    print(f"[smoke] built {sdist.name} via the in-tree backend")
    _run([sys.executable, "-m", "pip", "wheel", str(sdist),
          "--no-deps", "--wheel-dir", str(out_dir)])
    wheels = sorted(out_dir.glob("kp_sdlc-*.whl"))
    if len(wheels) != 1:
        raise SmokeFailure(f"expected exactly one kp_sdlc wheel, found {wheels}")
    return wheels[0]


def make_venv_with(wheel: Path, venv: Path) -> Path:
    _run([sys.executable, "-m", "venv", str(venv)])
    _run([_exe(venv, "python"), "-m", "pip", "install", "--quiet",
          "--no-deps", str(wheel)])
    return venv


def installed_payload_dir(venv: Path) -> Path:
    """Locate sdlc_init/_payload inside the venv, without importing it."""
    proc = _run([_exe(venv, "python"), "-c",
                 "import sdlc_init,pathlib;"
                 "print(pathlib.Path(sdlc_init.__file__).parent)"])
    return Path(proc.stdout.strip())


def check_init(venv: Path, workdir: Path, target: Path) -> dict:
    """Run `sdlc init` from outside any checkout and validate the result."""
    workdir.mkdir(parents=True, exist_ok=True)
    _run([_exe(venv, "sdlc"), "init",
          "--name", "ArtifactSmoke", "--owner", "@release-review",
          "--target", str(target), "--as-of", "2026-09-12"], cwd=workdir)

    missing = [rel for rel in BORN_ARTIFACTS if not (target / rel).exists()]
    if missing:
        raise SmokeFailure(f"born repo missing {len(missing)} artifact(s): {missing}")

    manifest = json.loads((target / ".harness" / "manifest.json").read_text("utf-8"))
    if manifest.get("status") != "ok":
        raise SmokeFailure(f"manifest status is {manifest.get('status')!r}, expected 'ok'")

    engine = manifest.get("engine", {})
    provenance = engine.get("provenance", {})
    if provenance.get("kind") != "package":
        raise SmokeFailure(
            f"installed artifact reported provenance {provenance!r}; "
            "an installed wheel must resolve to its packaged payload")
    if not str(provenance.get("payload_digest", "")).startswith("sha256:"):
        raise SmokeFailure(f"packaged provenance has no payload digest: {provenance!r}")
    if engine.get("sha") is not None:
        raise SmokeFailure(
            f"packaged install recorded a git sha ({engine['sha']!r}); a release "
            "artifact has no commit of its own and must not invent one")
    if not engine.get("vendored", {}).get("files"):
        raise SmokeFailure("manifest records no vendored engine files")
    return manifest


def check_bootstrap(venv: Path, workdir: Path, target: Path) -> None:
    """`sdlc bootstrap` — the copy-only path — gets the same install coverage."""
    target.mkdir(parents=True, exist_ok=True)
    _run([_exe(venv, "sdlc"), "bootstrap",
          "--target", str(target), "--as-of", "2026-09-12"], cwd=workdir)
    for rel in ("CLAUDE.md", "AGENTS.md", ".claude/skills"):
        if not (target / rel).exists():
            raise SmokeFailure(f"bootstrap did not install {rel}")


def check_planted_missing_asset(venv: Path, workdir: Path, target: Path,
                                relative_victim: str = PLANTED_VICTIM) -> str:
    """Delete one required payload asset; the next run must fail and name it.

    Restores the victim before returning, so the caller can plant a second one
    against the same install instead of rebuilding the whole artifact.
    """
    package_dir = installed_payload_dir(venv)
    victim = package_dir / relative_victim
    if not victim.is_file():
        raise SmokeFailure(f"planted victim absent before deletion: {victim}")
    kept = victim.read_bytes()
    victim.unlink()
    try:
        return _require_refusal(venv, workdir, target, relative_victim)
    finally:
        victim.write_bytes(kept)


def _require_refusal(venv: Path, workdir: Path, target: Path,
                     relative_victim: str) -> str:
    """The run must exit non-zero, name the victim, and write nothing."""

    proc = _run([_exe(venv, "sdlc"), "init",
                 "--name", "Planted", "--owner", "@release-review",
                 "--target", str(target), "--as-of", "2026-09-12"],
                cwd=workdir, check=False)
    if proc.returncode == 0:
        raise SmokeFailure(
            "init succeeded with a required asset removed — the completeness "
            "check is vacuous")
    combined = proc.stdout + proc.stderr
    wanted = relative_victim.split("_payload/", 1)[-1]
    if wanted not in combined:
        raise SmokeFailure(
            f"init failed but did not name the missing asset {wanted!r}:\n{combined}")
    if target.exists() and any(target.iterdir()):
        raise SmokeFailure(
            "init wrote into the target before failing the completeness check")
    return combined.strip().splitlines()[0] if combined.strip() else ""


def run(source: Path, workspace: Path) -> None:
    wheel = build_wheel(source, workspace / "wheelhouse")
    print(f"[smoke] built {wheel.name}")

    venv = make_venv_with(wheel, workspace / "venv")
    print("[smoke] installed non-editably into a clean venv")

    outside = workspace / "outside"
    manifest = check_init(venv, outside, workspace / "born")
    print(f"[smoke] sdlc init OK — provenance="
          f"{manifest['engine']['provenance']['kind']}, "
          f"vendored={manifest['engine']['vendored']['file_count']} files")

    check_bootstrap(venv, outside, workspace / "layered")
    print("[smoke] sdlc bootstrap OK")

    for index, victim in enumerate((PLANTED_VICTIM, PLANTED_NESTED_VICTIM)):
        first_line = check_planted_missing_asset(
            venv, outside, workspace / f"planted{index}", victim)
        print(f"[smoke] planted {victim} correctly refused: {first_line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=str(REPO_ROOT),
                        help="source tree to build the wheel from")
    parser.add_argument("--workspace", default=None,
                        help="scratch dir (default: a temp dir, removed after)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the workspace for inspection")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    if args.workspace:
        workspace = Path(args.workspace).resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        temp = None
    else:
        temp = tempfile.mkdtemp(prefix="kp-artifact-smoke-")
        workspace = Path(temp)

    try:
        run(source, workspace)
    except SmokeFailure as exc:
        print(f"[smoke] FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp and not args.keep:
            shutil.rmtree(temp, ignore_errors=True)

    print("[smoke] all artifact checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
