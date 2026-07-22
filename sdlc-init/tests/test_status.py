"""`sdlc status` reads the manifest record back — and must have teeth.

init has always written the `engine.vendored` sha256 pin; until now nothing
verified it, so the pin proved nothing. These tests hold the reader to the
two claims it makes:

  integrity — every way the vendored tree can diverge from its record is
              caught (edited, deleted, added), INCLUDING the manifest being
              hand-patched to match — the exact move someone makes when
              hand-updating a vendored file.
  upstream  — a repo born from an older engine is reported stale, with the
              changed files named.

Each has its anti-case. The false-positive guard (a runtime `__pycache__` or
a vendored `tests/` dir must never read as drift) matters as much as the
teeth: a status check that cries wolf gets ignored, and an ignored check is
the same as no check. And `unknown` must never aggregate to `ok` — a check
that was asked for and could not run has to fail closed.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# init shells out to QG/CK; keep those runs from littering the byte-exact
# vendored tree with caches.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_init import harness_map as hm
from sdlc_init import status as st
from sdlc_init.cli import main

ENGINE = Path(__file__).resolve().parents[2]  # KP_SDLC checkout

_template: list[Path] = []


def _tmpdir(prefix: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def _born_template() -> Path:
    """Init once. Every init runs the born-gated proof (two QG scans + a CK
    run), so mutating tests copy this tree rather than re-provisioning."""
    if not _template:
        tmp = _tmpdir("sdlc-status-src-")
        rc = main(["init", "--name", "Demo", "--owner", "@tester",
                   "--target", str(tmp), "--engine-root", str(ENGINE),
                   "--as-of", "2026-01-01"])
        assert rc == 0, f"sdlc init failed rc={rc} — cannot provision the template"
        _template.append(tmp)
    return _template[0]


def _fresh_repo() -> Path:
    dest = _tmpdir("sdlc-status-") / "repo"
    shutil.copytree(_born_template(), dest)
    return dest


def _fake_engine() -> Path:
    """A minimal, MUTABLE engine checkout carrying exactly the vendor
    sources — so a test can age the engine without touching the real one."""
    root = _tmpdir("sdlc-status-engine-")
    for src_rel, _ in hm.ENGINE_VENDOR_MAP:
        dest = root / src_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ENGINE / src_rel, dest)
    for src_rel, _ in hm.ENGINE_VENDOR_DIRS:
        shutil.copytree(ENGINE / src_rel, root / src_rel)
    return root


def _manifest(repo: Path) -> dict:
    return json.loads((repo / ".harness/manifest.json").read_text(encoding="utf-8"))


def _write_manifest(repo: Path, data: dict) -> None:
    (repo / ".harness/manifest.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _a_vendored_py(repo: Path) -> Path:
    """A real vendored source file to tamper with."""
    target = repo / "tools/qa/quality-gate/qg"
    files = sorted(p for p in target.glob("*.py") if p.is_file())
    assert files, "no vendored qg/*.py to tamper with — fixture assumption broke"
    return files[0]


# ── the clean baseline ────────────────────────────────────────────────

def test_clean_born_repo_is_ok_and_actually_compared_files():
    """A freshly born repo is green — and green because files were checked,
    not because the walker found nothing (the vacuous-pass anti-case)."""
    report = st.evaluate(_born_template())
    assert report["verdict"] == st.OK, report
    assert report["exit_code"] == 0
    assert report["integrity"]["verdict"] == st.OK
    assert report["integrity"]["checked"] > 50, (
        f"only {report['integrity']['checked']} files compared — the vendored "
        "walker is not seeing the tree, so OK would be vacuous")
    # Not asked for != checked and passed.
    assert report["upstream"]["verdict"] == st.NOT_CHECKED, report["upstream"]


def test_runtime_caches_and_test_dirs_are_not_drift():
    """ANTI-FALSE-POSITIVE: a __pycache__ (holding a .py, so the suffix
    filter alone cannot save us) and a vendored tests/ dir must not read as
    unexpected files. A status check that cries wolf gets ignored."""
    repo = _fresh_repo()
    cache = repo / "tools/qa/quality-gate/qg/__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "stale.py").write_text("# cache artifact\n", encoding="utf-8")
    tests = repo / "tools/qa/cathedral-keeper/cathedral_keeper/tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_local.py").write_text("# local test\n", encoding="utf-8")
    report = st.evaluate(repo)
    assert report["verdict"] == st.OK, (
        f"pruned paths leaked into drift: {report['integrity']}")


# ── integrity teeth ───────────────────────────────────────────────────

def test_tampered_vendored_file_is_detected():
    """The core claim: an edited vendored engine file is caught and named."""
    repo = _fresh_repo()
    victim = _a_vendored_py(repo)
    victim.write_bytes(victim.read_bytes() + b"\n# local edit\n")
    report = st.evaluate(repo)
    assert report["verdict"] == st.DRIFT, report
    assert report["exit_code"] == 1
    rel = victim.relative_to(repo).as_posix()
    assert rel in report["integrity"]["modified"], report["integrity"]


def test_deleted_vendored_file_is_detected():
    repo = _fresh_repo()
    victim = _a_vendored_py(repo)
    rel = victim.relative_to(repo).as_posix()
    victim.unlink()
    report = st.evaluate(repo)
    assert report["verdict"] == st.DRIFT
    assert rel in report["integrity"]["missing"], report["integrity"]


def test_added_vendored_file_is_detected():
    repo = _fresh_repo()
    planted = repo / "tools/qa/quality-gate/qg/injected.py"
    planted.write_text("# smuggled into the engine\n", encoding="utf-8")
    report = st.evaluate(repo)
    assert report["verdict"] == st.DRIFT
    assert "tools/qa/quality-gate/qg/injected.py" in report["integrity"]["extra"], \
        report["integrity"]


def test_hand_patched_manifest_is_detected():
    """The realistic evasion: someone edits a vendored file AND patches the
    per-file digest so integrity would pass. The aggregate no longer digests
    its own files map, and that is the tell."""
    repo = _fresh_repo()
    victim = _a_vendored_py(repo)
    victim.write_bytes(victim.read_bytes() + b"\n# local edit\n")
    rel = victim.relative_to(repo).as_posix()
    data = _manifest(repo)
    data["engine"]["vendored"]["files"][rel] = hashlib.sha256(
        victim.read_bytes()).hexdigest()   # patched to match the tampered file
    _write_manifest(repo, data)            # ...but the aggregate is untouched
    report = st.evaluate(repo)
    assert report["verdict"] == st.DRIFT, (
        "a hand-patched digest passed unnoticed — the aggregate self-check "
        "is not doing its job")
    assert "hand" in report["integrity"]["reason"], report["integrity"]


# ── upstream / staleness teeth ────────────────────────────────────────

def test_upstream_clean_against_the_engine_it_was_born_from():
    report = st.evaluate(_born_template(), ENGINE)
    assert report["upstream"]["verdict"] == st.OK, report["upstream"]
    assert report["upstream"]["compared"] > 50
    assert report["verdict"] == st.OK
    assert report["exit_code"] == 0


def test_stale_snapshot_is_detected_and_names_the_changed_file():
    """Age the ENGINE (not the repo): integrity stays clean, upstream goes
    drift and names the file — the 'you are running last month's gate'
    signal that did not exist before."""
    repo = _fresh_repo()
    engine = _fake_engine()
    moved = engine / "quality-gate/qg/checks_observability.py"
    assert moved.is_file(), "fixture assumption broke: vendored check missing"
    moved.write_bytes(moved.read_bytes() + b"\n# upstream fix\n")
    report = st.evaluate(repo, engine)
    assert report["integrity"]["verdict"] == st.OK, (
        "aging the engine must not implicate the repo's own bytes")
    assert report["upstream"]["verdict"] == st.DRIFT, report["upstream"]
    assert "tools/qa/quality-gate/qg/checks_observability.py" \
        in report["upstream"]["changed"], report["upstream"]
    assert report["exit_code"] == 1


def test_new_upstream_file_reported_as_added():
    repo = _fresh_repo()
    engine = _fake_engine()
    (engine / "quality-gate/qg/checks_new_rule.py").write_text(
        "# a check added after this repo was born\n", encoding="utf-8")
    report = st.evaluate(repo, engine)
    assert report["upstream"]["verdict"] == st.DRIFT
    assert "tools/qa/quality-gate/qg/checks_new_rule.py" \
        in report["upstream"]["added"], report["upstream"]


# ── fail-closed ───────────────────────────────────────────────────────

def test_missing_manifest_is_unknown_not_ok():
    empty = _tmpdir("sdlc-status-empty-")
    report = st.evaluate(empty)
    assert report["verdict"] == st.UNKNOWN
    assert report["exit_code"] == 2, "a repo we cannot verify must not exit 0"


def test_unusable_engine_root_is_unknown_and_outranks_a_clean_integrity():
    """Asking for the upstream check and not getting it must not report
    green just because the local tree happened to be intact."""
    not_an_engine = _tmpdir("sdlc-status-notengine-")
    report = st.evaluate(_born_template(), not_an_engine)
    assert report["integrity"]["verdict"] == st.OK
    assert report["upstream"]["verdict"] == st.UNKNOWN, report["upstream"]
    assert report["verdict"] == st.UNKNOWN
    assert report["exit_code"] == 2


def test_corrupt_manifest_is_unknown():
    repo = _fresh_repo()
    (repo / ".harness/manifest.json").write_text("{ not json", encoding="utf-8")
    report = st.evaluate(repo)
    assert report["verdict"] == st.UNKNOWN
    assert report["exit_code"] == 2


# ── CLI wiring ────────────────────────────────────────────────────────

def test_cli_status_is_wired_and_emits_parseable_json(capsys):
    rc = main(["status", "--target", str(_born_template()), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == st.SCHEMA
    assert payload["verdict"] == st.OK
    assert payload["manifest"]["project_name"] == "Demo"


def test_cli_status_exit_code_propagates_drift(capsys):
    repo = _fresh_repo()
    victim = _a_vendored_py(repo)
    victim.write_bytes(victim.read_bytes() + b"\n# local edit\n")
    rc = main(["status", "--target", str(repo)])
    assert rc == 1, "drift must reach the shell as a non-zero exit"
    assert "DRIFT" in capsys.readouterr().out
