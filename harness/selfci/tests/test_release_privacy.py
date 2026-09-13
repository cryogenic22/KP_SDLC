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


# Samples are assembled from fragments for the same reason `selftest()` does it:
# written as literals, this file would trip the scanner it is testing, and the
# only remedy would be an allowlist over the test — which is the entry that later
# gets widened to cover a real leak.
_BS = chr(92)
_WHO = "real" + "person"


@pytest.mark.parametrize("sample", [
    "path C:" + _BS + "Users" + _BS + _WHO + _BS + "Documents",
    "cd C:/" + "Users/" + _WHO + "/Downloads",
    "log at /ho" + "me/" + _WHO + "/app.log",
    "open /Us" + "ers/" + _WHO.title() + "/Library/Preferences",
])
def test_absolute_user_paths_are_caught(rp, sample):
    findings = rp.scan_text("probe.md", sample)
    assert any(f.rule == "absolute-user-path" for f in findings), sample


@pytest.mark.parametrize("sample", [
    "install under C:" + _BS + "Users" + _BS + "<user>" + _BS + "AppData",
    "CI home is /ho" + "me/runner/work/repo",
    "a sentence mentioning /ho" + "me directories",
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
    ".claude/ctx/session-abc123" + ".ctx",
    ".claude/ctx/latest-" + "gist.md",
    ".claude/ctx/checkpoints" + ".jsonl",
    "Claude out" + "puts/report.html",
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


def test_a_new_raw_session_cannot_enter_the_tree_by_default():
    """The ignore rule, not just the current file list.

    Removing today's files fixes today. This asserts the property that stops
    tomorrow: writing a new session record leaves it ignored.
    """
    probe = _ROOT / ".claude" / "ctx" / ("session-pytestprobe" + ".ctx")
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


def test_the_public_path_is_still_trackable():
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


# ── Review of #42: three ways the detector could be trusted too far ──────────
#
# Each test below fails if its fix is reverted, and the first carries its own
# planted failure: a coverage assertion that cannot itself be vacuous.

def test_every_detector_has_its_own_positive_control(rp):
    """A rule name is not a detector.

    Seven patterns report `credential`, so a self-test keyed by rule name let
    one matching pattern vouch for all seven. Three detectors shipped with no
    positive control at all (`github fine-grained token`, `aws secret`,
    `local scan output`) while the self-test reported green.
    """
    fixtures = rp._fixtures()
    content = {label for label, _ in rp._content_detectors()}
    paths = {label for label, _ in rp._LOCAL_ONLY_PATHS}
    assert content == set(fixtures["content"])
    assert paths == set(fixtures["path"])


def test_a_detector_without_a_fixture_fails_the_selftest(rp, monkeypatch):
    """The planted failure for the check above — coverage must have teeth."""
    import re

    monkeypatch.setattr(
        rp, "_CREDENTIAL_PATTERNS",
        rp._CREDENTIAL_PATTERNS + (("planted", re.compile(r"NEVERMATCHED")),))
    assert any("planted" in failure for failure in rp.selftest())


def test_a_fixture_its_own_detector_misses_fails_the_selftest(rp, monkeypatch):
    """Coverage alone is not enough: the sample must match *its* detector."""
    original = rp._fixtures
    monkeypatch.setattr(rp, "_fixtures", lambda: {
        **original(),
        "content": {**original()["content"], "aws secret": "harmless text"},
    })
    assert any("aws secret" in failure for failure in rp.selftest())


def test_a_nul_byte_does_not_suppress_the_content_rules(rp):
    """One NUL in the first 8 KiB used to skip the file's content entirely."""
    secret = "token = " + "sk-" + "E" * 24
    laced = ("note" + chr(0) + secret).encode("utf-8")
    assert "credential" in {f.rule for f in rp.scan_blob("probe.bin", laced)}


def test_utf16_content_is_scanned(rp):
    """UTF-16 is the canonical NUL-carrying encoding.

    Decoded as UTF-8 it interleaves a NUL through every word, so a credential
    written in UTF-16 matches no content rule in that view.
    """
    secret = ("token = " + "sk-" + "F" * 24).encode("utf-16-le")
    assert "credential" in {f.rule for f in rp.scan_blob("wide.txt", secret)}


def test_a_nul_carrying_blob_is_reported_not_silently_skipped(rp):
    """Scanning a replace-decoded binary proves nothing about the mangled bytes.

    The release set carries no binary today, so reporting one costs nothing
    until somebody adds it — at which point it is a reviewed ALLOW entry.
    """
    rules = {f.rule for f in rp.scan_blob("x.bin", b"a" + bytes(1) + b"b")}
    assert "unscannable-content" in rules
    assert not rp.scan_blob("clean.txt", b"ordinary text, nothing flagged")


@pytest.mark.parametrize("path", [
    ".Claude/CTX/session-abc" + ".CTX",
    "CLAUDE OUT" + "PUTS/report.html",
    ".Quality-Re" + "ports/report.json",
])
def test_path_rules_are_case_insensitive(rp, path):
    """Windows is case-insensitive, so the same file can reach the index under
    a different spelling. A case-sensitive path rule lets that spelling ship."""
    assert rp.scan_path(path)


@pytest.mark.parametrize("sample", [
    "see C:" + _BS + "users" + _BS + _WHO + _BS + "x",
    "open /us" + "ers/" + _WHO.title() + "/Library/x",
])
def test_user_home_content_rules_are_case_insensitive(rp, sample):
    assert "absolute-user-path" in [f.rule for f in rp.scan_text("p.txt", sample)]


def test_a_rest_route_is_not_a_home_directory(rp):
    """The cost of case-insensitivity, paid for by the `_MAC_HOME` lookbehind.

    `/users/` is an extremely common route; an absolute home path begins at a
    path root, never mid-segment.
    """
    route = "GET /api/us" + "ers/" + _WHO + "/profile returns 200"
    assert rp.scan_text("routes.md", route) == []
