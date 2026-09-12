"""Engine-root resolution and the asset contract `sdlc init` depends on.

`sdlc init` and `sdlc bootstrap` read two kinds of thing from an "engine root":
the harness tree that `copy_harness` installs, and the QG/CK sources that
`vendor_engine` byte-copies. In a git checkout those sit beside each other at
the repository root. In an installed wheel they have to be carried explicitly,
because a wheel ships importable packages and nothing else.

Before this module the default was `Path(__file__).resolve().parents[2]`, which
is the checkout layout and, from `site-packages/sdlc_init/cli.py`, resolves to
the environment's `Lib/` directory. A non-editable install therefore failed at
`InitManifest.validate()` with "engine_root has no harness/ dir", and the only
smoke coverage was `-h`, so CI stayed green (issue #38).

Two rules make this fail loudly instead of late:

* resolution names its own provenance — `package` or `checkout` — and the
  manifest records which one was used, so a born repo can tell a released
  artifact from someone's working tree;
* every asset the map requires is checked up front, and a missing one is named.
  A payload that is present but incomplete is the failure a packaging change is
  most likely to introduce, and it must not be discovered halfway through a
  phase that has already written files.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from . import harness_map as hm

# The staged payload inside the installed package. Built by the in-tree build
# backend (build_support/kp_build_backend.py); absent from a git checkout,
# which is exactly how the two provenances are told apart.
PAYLOAD_DIRNAME = "_payload"

# Top-level component dirs an engine root must carry. `InitManifest.validate`
# enforces the same three; this is the single list both read.
REQUIRED_COMPONENTS: tuple[str, ...] = ("harness", "quality-gate", "cathedral-keeper")

PROVENANCE_PACKAGE = "package"
PROVENANCE_CHECKOUT = "checkout"


def required_assets() -> tuple[str, ...]:
    """Every engine-root-relative path the harness map consumes.

    Derived from `harness_map` rather than restated, so adding a template or a
    vendored engine file cannot silently drop out of the packaged payload: the
    map is the one place the file set is declared, and the packaging test walks
    this function.
    """
    paths: list[str] = [f"harness/{hm.SKILLS_SRC}"]
    paths += [f"harness/{src}" for src, _dest in hm.FILE_MAP]
    paths += [f"harness/{src}" for src, _dest in hm.DIR_MAP]
    paths += [src for src, _dest in hm.ENGINE_VENDOR_MAP]
    paths += [src for src, _dest in hm.ENGINE_VENDOR_DIRS]
    # dict.fromkeys: stable order, no duplicates.
    return tuple(dict.fromkeys(paths))


def missing_assets(engine_root: Path) -> list[str]:
    """Required paths absent from `engine_root`, in declaration order."""
    return [rel for rel in required_assets() if not (engine_root / rel).exists()]


def payload_digest(engine_root: Path) -> str:
    """sha256 over the payload's file set: every required asset's relative path
    and content digest, sorted. Two installs of one release agree; a tampered
    or partial payload does not.

    Directories are walked in sorted order so the digest is reproducible across
    filesystems that enumerate differently.
    """
    entries: list[tuple[str, str]] = []
    for rel in required_assets():
        source = engine_root / rel
        if source.is_dir():
            for child in sorted(source.rglob("*")):
                if child.is_file():
                    entries.append(
                        (child.relative_to(engine_root).as_posix(), _file_sha256(child))
                    )
        elif source.is_file():
            entries.append((rel, _file_sha256(source)))
    ordered = sorted(entries)
    return hashlib.sha256(
        "".join(f"{rel}:{digest}\n" for rel, digest in ordered).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _package_version() -> str:
    """Installed distribution version, or 'unknown' outside an install.

    Never falls back to a git SHA: issue #38 requires a packaged install to say
    what it is rather than impersonate a checkout.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8 is out of support
        return "unknown"
    try:
        return version("kp-sdlc")
    except PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True)
class EngineRoot:
    """A resolved engine root and how it was found."""

    path: Path
    provenance: str
    package_version: str = "unknown"

    @property
    def is_package(self) -> bool:
        return self.provenance == PROVENANCE_PACKAGE


def packaged_root() -> Path | None:
    """The staged payload inside this installed package, if it is present."""
    candidate = Path(__file__).resolve().parent / PAYLOAD_DIRNAME
    return candidate if candidate.is_dir() else None


def checkout_root() -> Path | None:
    """The source checkout this module was imported from, if it looks like one."""
    candidate = Path(__file__).resolve().parents[2]
    if all((candidate / component).is_dir() for component in REQUIRED_COMPONENTS):
        return candidate
    return None


def resolve(explicit: str | Path | None = None) -> EngineRoot:
    """Resolve the engine root, preferring an explicit path.

    Order: an explicit `--engine-root`, then the packaged payload, then the
    surrounding checkout. An explicit path is trusted for *location* only — it
    is still asset-checked by the caller, so pointing at an empty directory
    fails with a named missing asset rather than part-way through a phase.
    """
    if explicit is not None:
        return EngineRoot(Path(explicit).resolve(), PROVENANCE_CHECKOUT,
                          _package_version())
    packaged = packaged_root()
    if packaged is not None:
        return EngineRoot(packaged, PROVENANCE_PACKAGE, _package_version())
    checkout = checkout_root()
    if checkout is not None:
        return EngineRoot(checkout, PROVENANCE_CHECKOUT, _package_version())
    raise SystemExit(
        "error: cannot locate a KP_SDLC engine root.\n"
        "  This install carries no packaged payload and is not inside a "
        "source checkout.\n"
        "  Pass --engine-root /path/to/KP_SDLC, or reinstall a release "
        "artifact built with the in-tree build backend."
    )


def require_complete(root: EngineRoot) -> None:
    """Fail with the first missing assets named, before any phase writes."""
    missing = missing_assets(root.path)
    if not missing:
        return
    shown = "\n".join(f"    {rel}" for rel in missing[:10])
    more = "" if len(missing) <= 10 else f"\n    ... and {len(missing) - 10} more"
    raise SystemExit(
        f"error: engine root is incomplete ({root.provenance}): {root.path}\n"
        f"  {len(missing)} required asset(s) missing:\n{shown}{more}\n"
        "  A packaged install must be built with the in-tree build backend so "
        "harness/ and the vendored engine sources are staged into the wheel."
    )


def provenance_record(root: EngineRoot) -> dict:
    """The manifest block distinguishing a released artifact from a checkout.

    A packaged root records the distribution version and a digest over the
    payload file set. It does **not** record a git SHA: there is no commit to
    name, and inventing one would make a released artifact indistinguishable
    from the tree it was built from.
    """
    record = {"kind": root.provenance, "package_version": root.package_version}
    if root.is_package:
        record["payload_digest"] = f"sha256:{payload_digest(root.path)}"
    return record
