"""The release archive carries product source, not operational memory (#39).

Two things are tested, and the order matters. First that the detector works —
because the bug that hid #39 for as long as it hid was a scan whose own pattern
matched nothing, so a clean report meant nothing. Only then that the tree is
clean.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_SCANNER = _ROOT / "harness" / "selfci" / "release_privacy.py"


def _load():
    spec = importlib.util.spec_from_file_location("release_privacy", _SCANNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_privacy"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def rp():
    return _load()


# ── The detector must be able to fail ────────────────────────────────────────

def test_detector_selftest_passes(rp):
    """Every rule matches a known positive and rejects a known negative.

    This is the guard against the specific way the original investigation went
    wrong: a shell-escaped `C:\\\\Users\\\\` reached grep as `C:\\Users\\`, the
    `\\U` degraded to a literal, the pattern matched nothing, and the empty
    result read as safety.
    """
    assert rp.selftest() == []


@pytest.mark.parametrize("sample", [
    r"path C:\Users\realperson\Documents\thing",
    "cd C:/Users/realperson/Downloads",
    "log at /home/realperson/app.log",
    "open /Users/RealPerson/Library/Preferences",
])
def test_absolute_user_paths_are_caught(rp, sample):
    findings = rp.scan_text("probe.md", sample)
    assert any(f.rule == "absolute-user-path" for f in findings), sample


@pytest.mark.parametrize("sample", [
    r"install under C:\Users\<user>\AppData",
    "CI home is /home/runner/work/repo",
    "a sentence mentioning /home directories",
])
def test_placeholder_and_ci_paths_are_not_flagged(rp, sample):
    """Documentation must stay writable. A rule that flags `<user>` gets muted."""
    assert [f for f in rp.scan_text("probe.md", sample) if
            f.rule == "absolute-user-path"] == []


def test_credential_shapes_are_caught_without_echoing_them(rp):
    secret = "sk-" + "Z" * 30
    findings = rp.scan_text("probe.md", f"key = {secret}")
    assert any(f.rule == "credential" for f in findings)
    # The report must never carry the secret it found.
    for finding in findings:
        assert secret not in finding.detail
        assert secret not in str(finding.as_dict())


@pytest.mark.parametrize("path", [
    ".claude/ctx/session-abc123.ctx",
    ".claude/ctx/latest-gist.md",
    ".claude/ctx/checkpoints.jsonl",
    "Claude outputs/report.html",
])
def test_local_only_paths_are_caught_by_shape(rp, path):
    assert rp.scan_path(path), path


@pytest.mark.parametrize("path", [
    ".claude/settings.json",
    ".claude/ctx/public/README.md",
    "docs/decisions/0004-ctxpack-memory-scopes.md",
])
def test_public_and_product_paths_are_not_flagged(rp, path):
    assert rp.scan_path(path) == []


# ── Only then: the tree itself ───────────────────────────────────────────────

def test_release_tree_is_clean(rp):
    findings = rp.scan("HEAD", _ROOT)
    assert findings == [], rp._report(findings)


def test_raw_session_memory_is_not_tracked():
    """The specific regression #39 names, asserted against git rather than disk."""
    out = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", ".claude/ctx/"],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.split()
    unexpected = [p for p in out if not p.startswith(".claude/ctx/public/")]
    assert unexpected == [], (
        f"raw CtxPack artifacts are tracked and would ship: {unexpected}")


def test_a_new_raw_session_cannot_enter_the_tree_by_default(tmp_path):
    """The ignore rule, not just the current file list.

    Removing today's files fixes today. This asserts the property that stops
    tomorrow: writing a new session record leaves it ignored.
    """
    probe = _ROOT / ".claude" / "ctx" / "session-pytestprobe.ctx"
    probe.write_text("probe", encoding="utf-8")
    try:
        result = subprocess.run(
            ["git", "-C", str(_ROOT), "check-ignore", str(probe)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode == 0, (
            "a newly written raw session record is NOT ignored — it would be "
            "tracked on the next `git add -A` and ship in the release archive")
    finally:
        probe.unlink(missing_ok=True)


def test_the_public_path_is_still_trackable(tmp_path):
    """The other half: the allowlisted path must not be swept up by the ignore."""
    probe = _ROOT / ".claude" / "ctx" / "public" / "_pytest_probe.md"
    probe.write_text("probe", encoding="utf-8")
    try:
        result = subprocess.run(
            ["git", "-C", str(_ROOT), "check-ignore", str(probe)],
            capture_output=True, text=True, encoding="utf-8",
        )
        assert result.returncode != 0, (
            ".claude/ctx/public/ is ignored — public memory would be "
            "unpublishable, which makes the scope model a dead letter")
    finally:
        probe.unlink(missing_ok=True)
