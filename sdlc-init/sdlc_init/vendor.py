"""Engine-vendoring enumeration — the one walker over the vendored tree.

`vendor_engine` (what init WRITES) and `sdlc status` (what it later
VERIFIES) must agree on exactly which files constitute the vendored engine.
Two walkers would rot apart, and the failure is silent in the dangerous
direction: a file init vendors but status never enumerates is a file that
can be edited forever without tripping the tamper check — drift detection
that reads green because it never looked. So both consume this module.

`iter_vendor_files` walks the ENGINE sources (what should be there);
`iter_installed_files` walks a born repo's tools/qa/ (what is there). Both
apply the same suffix/prune filter, so a runtime `__pycache__` or a vendored
`tests/` dir can never read as an unexpected extra file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

from . import harness_map as hm


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def missing_vendor_sources(engine_root: Path) -> list[str]:
    """Engine components the vendor maps expect but the checkout lacks."""
    missing = [src for src, _ in hm.ENGINE_VENDOR_MAP
               if not (engine_root / src).is_file()]
    missing += [src for src, _ in hm.ENGINE_VENDOR_DIRS
                if not (engine_root / src).is_dir()]
    return missing


def _keep(path: Path, rel: Path) -> bool:
    """The vendoring filter: code+config only, caches and test trees pruned
    (which also sidesteps stray non-code files like Windows' 'nul')."""
    if not path.is_file() or path.suffix not in hm.VENDOR_INCLUDE_SUFFIXES:
        return False
    return not (hm.VENDOR_PRUNE_DIRS & set(rel.parts))


def iter_vendor_dir(src_dir: Path, dest_dir_rel: str) -> Iterator[tuple[Path, str]]:
    """Yield (source, dest_rel) for one vendored directory."""
    for f in sorted(src_dir.rglob("*")):
        rel = f.relative_to(src_dir)
        if _keep(f, rel):
            yield f, f"{dest_dir_rel}/{rel.as_posix()}"


def iter_vendor_files(engine_root: Path) -> Iterator[tuple[Path, str]]:
    """Yield (source, dest_rel) for every file to vendor: the explicit map,
    then the directory fan-outs (each walked by iter_vendor_dir)."""
    for src_rel, dest_rel in hm.ENGINE_VENDOR_MAP:
        yield engine_root / src_rel, dest_rel
    for src_dir_rel, dest_dir_rel in hm.ENGINE_VENDOR_DIRS:
        yield from iter_vendor_dir(engine_root / src_dir_rel, dest_dir_rel)


def iter_installed_files(target: Path) -> Iterator[tuple[Path, str]]:
    """Yield (path, dest_rel) for the vendored tree as it exists ON DISK in a
    born repo — the same filter iter_vendor_files applies to the sources."""
    root = target / hm.ENGINE_VENDOR_DEST
    if not root.is_dir():
        return
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if _keep(f, rel):
            yield f, f"{hm.ENGINE_VENDOR_DEST}/{rel.as_posix()}"


def hash_engine_sources(engine_root: Path) -> dict[str, str]:
    """dest_rel -> sha256 of the CURRENT engine source bytes (what a repo
    vendored today would receive)."""
    return {dest_rel: sha256_bytes(src.read_bytes())
            for src, dest_rel in iter_vendor_files(engine_root)}


def hash_installed(target: Path) -> dict[str, str]:
    """dest_rel -> sha256 of the vendored bytes a born repo actually holds."""
    return {dest_rel: sha256_bytes(path.read_bytes())
            for path, dest_rel in iter_installed_files(target)}
