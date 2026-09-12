"""In-tree PEP 517 backend: stage the engine payload, then build normally.

`sdlc init` needs the harness tree and the QG/CK sources that `vendor_engine`
byte-copies. A wheel ships importable packages, so those assets have to be
carried as package data — but they must not be *duplicated in the repository*,
because the engine sources are the single copy the manifest's per-file sha256
is meaningful against.

So they are staged at build time into `sdlc-init/sdlc_init/_payload/`, laid out
exactly as an engine root, and that directory is gitignored. A checkout has no
payload and resolves to itself; an installed wheel has one and resolves to it
(`sdlc_init.engine_assets`).

Staging copies bytes verbatim — no substitution, no newline translation — so a
vendored file in a born repo hashes identically whether it came from a release
artifact or a checkout.

Wired via:

    [build-system]
    build-backend = "kp_build_backend"
    backend-path = ["build_support"]

Everything setuptools defines is re-exported; only the two build hooks are
wrapped.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from setuptools import build_meta as _setuptools

# Re-export the full PEP 517 surface so any hook we do not wrap still resolves.
# pylint: disable=unused-import
from setuptools.build_meta import (  # noqa: F401
    build_editable,
    get_requires_for_build_editable,
    get_requires_for_build_sdist,
    get_requires_for_build_wheel,
    prepare_metadata_for_build_editable,
    prepare_metadata_for_build_wheel,
)

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "sdlc-init" / "sdlc_init" / "_payload"

# Whole-tree copies, pruned. harness/ is the born repo's entire install source.
TREE_SOURCES: tuple[str, ...] = ("harness",)

# Engine sources vendor_engine byte-copies. Kept in step with
# harness_map.ENGINE_VENDOR_MAP / ENGINE_VENDOR_DIRS by a packaging test that
# walks sdlc_init.engine_assets.required_assets().
FILE_SOURCES: tuple[str, ...] = (
    "quality-gate/quality_gate.py",
    "quality-gate/quality-gate.config.json",
    "cathedral-keeper/ck.py",
    "cathedral-keeper/cathedral-keeper.config.json",
)
DIR_SOURCES: tuple[str, ...] = (
    "quality-gate/qg",
    "cathedral-keeper/cathedral_keeper",
)

PRUNE_DIRS = frozenset({"__pycache__", "tests", ".pytest_cache", ".mypy_cache"})
# Engine dirs ship code and config only; the wholesale copy that would also
# carry caches and the stray Windows-reserved 'nul' file is the thing the
# vendoring filter exists to prevent.
ENGINE_SUFFIXES = (".py", ".json")


def _copy_tree(src: Path, dest: Path, *, suffixes: tuple[str, ...] | None = None) -> int:
    copied = 0
    for child in sorted(src.rglob("*")):
        if any(part in PRUNE_DIRS for part in child.relative_to(src).parts):
            continue
        if not child.is_file():
            continue
        if suffixes is not None and child.suffix not in suffixes:
            continue
        target = dest / child.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(child, target)  # bytes verbatim
        copied += 1
    return copied


def stage_payload() -> int:
    """Rebuild the payload from scratch. Returns the file count staged."""
    if PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    PAYLOAD.mkdir(parents=True)

    total = 0
    for rel in TREE_SOURCES:
        source = ROOT / rel
        if not source.is_dir():
            raise RuntimeError(f"cannot stage payload: missing {rel}/ at {ROOT}")
        total += _copy_tree(source, PAYLOAD / rel)

    for rel in FILE_SOURCES:
        source = ROOT / rel
        if not source.is_file():
            raise RuntimeError(f"cannot stage payload: missing {rel} at {ROOT}")
        target = PAYLOAD / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        total += 1

    for rel in DIR_SOURCES:
        source = ROOT / rel
        if not source.is_dir():
            raise RuntimeError(f"cannot stage payload: missing {rel}/ at {ROOT}")
        total += _copy_tree(source, PAYLOAD / rel, suffixes=ENGINE_SUFFIXES)

    print(f"[kp-build] staged {total} payload files into {PAYLOAD}", file=sys.stderr)
    return total


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    stage_payload()
    return _setuptools.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    stage_payload()
    return _setuptools.build_sdist(sdist_directory, config_settings)


if __name__ == "__main__":  # `python build_support/kp_build_backend.py` stages only
    stage_payload()
