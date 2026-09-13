"""Issue #35 — the same `--root` must mean the same scan from any cwd.

Run at the subprocess level against two *populated* directories holding the
same relative paths, because that is the only shape that reproduces the
defect. An empty external cwd is not a sufficient anti-case: QG's cwd-first
candidate does not exist there, so it falls back to `--root` and the run looks
correct for the wrong reason.

What went wrong: `QualityGate.get_files_to_check` resolved a relative path
against `Path.cwd()` whenever that candidate existed, and CK's integration
launched QG without `cwd=root`. Running CK from a second checkout of the same
commit therefore scanned *that* checkout, and the evidence paths it emitted
could not match the target root's committed baseline keys -- 78 findings
upgraded to high severity, same SHA, same `--root`, exit 1 instead of 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QG = REPO_ROOT / "quality-gate" / "quality_gate.py"

# Trips at least one QG rule in both trees, so a scan of either produces
# findings and "which tree did it read" is answerable from the output.
_SHARED = (
    "import os\n"
    "def handler():\n"
    "    try:\n"
    "        risky()\n"
    "    except:\n"
    "        pass\n"
)
# Present only in B. If a run anchored at A reports it, the wrong tree was read.
_ONLY_IN_B = "\ndef only_in_b():\n    return 'B' * 120\n"


@pytest.fixture
def two_trees(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Two populated roots sharing one relative path, plus a paths manifest."""
    a, b = tmp_path / "A", tmp_path / "B"
    for root in (a, b):
        (root / "src").mkdir(parents=True)
        (root / "src" / "mod.py").write_text(_SHARED, encoding="utf-8")
    (b / "src" / "mod.py").write_text(_SHARED + _ONLY_IN_B, encoding="utf-8")

    listing = tmp_path / "paths.txt"
    listing.write_text("src/mod.py\n", encoding="utf-8")
    return a, b, listing


def _audit(root: Path, listing: Path, cwd: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(QG), "--root", str(root), "--mode", "audit",
         "--json", "--paths-from", str(listing)],
        capture_output=True, text=True, cwd=str(cwd), timeout=180,
    )
    assert proc.returncode == 0, f"audit exited {proc.returncode}: {proc.stderr[:400]}"
    return json.loads(proc.stdout)


def test_same_root_scans_the_same_tree_from_either_cwd(two_trees):
    """The acceptance criterion, stated directly."""
    a, b, listing = two_trees

    from_a = _audit(a, listing, cwd=a)
    from_b = _audit(a, listing, cwd=b)

    assert from_a["stats"]["files_checked"] == from_b["stats"]["files_checked"]
    assert _fingerprint(from_a) == _fingerprint(from_b)


def test_a_foreign_cwd_cannot_redirect_the_scan(two_trees):
    """The planted failure: B's extra content must never appear in an A scan.

    This is what the old behaviour did -- and it is a sharper check than
    comparing the two runs to each other, which a bug that redirected *both*
    runs identically would still satisfy.
    """
    a, b, listing = two_trees

    scanned = {issue["file"] for issue in _audit(a, listing, cwd=b)["issues"]}
    assert scanned, "the scan produced no findings, so it proves nothing"
    for path in scanned:
        normalised = path.replace("\\", "/")
        assert ".." not in normalised, f"scan escaped --root: {path}"
        assert (a / normalised).exists(), f"{path} is not a file under {a}"


def test_an_unresolvable_manifest_fails_closed(tmp_path):
    """Anchoring to `--root` must not create a quieter hole than it closed.

    Explicit paths that match no code file are a legitimate no-op that passes
    (a docs-only change). A manifest whose entries resolve nowhere under the
    root is not that -- it is a scan of nothing -- so it exits 2.
    """
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "mod.py").write_text(_SHARED, encoding="utf-8")

    listing = tmp_path / "paths.txt"
    listing.write_text("nowhere/absent.py\n", encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(QG), "--root", str(root), "--mode", "audit",
         "--json", "--paths-from", str(listing)],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=180,
    )
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}"
    assert "--paths-from" in proc.stderr


def test_absolute_entries_are_still_honoured(two_trees):
    """An absolute entry means what it says, wherever it points."""
    a, b, _ = two_trees
    listing = b / "abs.txt"
    listing.write_text(str(b / "src" / "mod.py") + "\n", encoding="utf-8")

    payload = _audit(b, listing, cwd=a)
    assert payload["stats"]["files_checked"] == 1


def _fingerprint(payload: dict) -> list[tuple]:
    return sorted((issue["file"].replace("\\", "/"), issue["line"], issue["rule"])
                  for issue in payload["issues"])


# ── The acceptance criterion at CK's own entry point ─────────────────────────

CK = REPO_ROOT / "cathedral-keeper" / "ck.py"

# `(ctx.root / qg_path).resolve()` keeps an absolute qg_path as-is, so the
# fixture points CK at the engine in *this* tree. Pointing it at a copy would
# be worse than useless: a copy taken from a fixed tree stays fixed while the
# engine under test is reverted, and the planted failure then passes for a
# reason that has nothing to do with the code under test.
_CK_CONFIG = {"integrations": {"quality_gate": {"enabled": True,
                                                "qg_path": str(QG)}}}

# Only in B, and chosen to move QG's own numbers: a hardcoded secret is an
# error, so a run that reads B instead of A reports a different PRS and error
# count rather than merely different paths.
#
# Assembled so that no line of *this* file reads as an assignment of a secret.
# Written plainly, the engine flags its own test fixture -- which it did, and
# only after the commit, because QG scans tracked files and an untracked new
# file is never seen.
_SECRET_NAME = "pass" + "word"
_SECRET_VALUE = '"' + "hunter2" * 2 + '"'
_ONLY_IN_B_SECRET = ("\ndef only_in_b():\n    "
                     + _SECRET_NAME + " = " + _SECRET_VALUE + "\n")


def _ck_summary(root: Path, cwd: Path, out: Path) -> list[tuple]:
    subprocess.run(
        [sys.executable, str(CK), "analyze", "--root", str(root),
         "--mode", "repo", "--out-json", str(out)],
        capture_output=True, text=True, cwd=str(cwd), timeout=300,
    )
    findings = json.loads(out.read_text(encoding="utf-8"))["findings"]
    return sorted(
        (f["policy_id"], f["severity"], (f.get("metadata") or {}).get("prs"),
         (f.get("metadata") or {}).get("errors"))
        for f in findings
    )


def test_ck_analyze_is_identical_from_either_cwd(tmp_path):
    """Issue #35 as reported: same SHA, same absolute --root, two cwds.

    The reported symptom was exit 0 from the target worktree and exit 1 from a
    second one, with `CK-INTEGRATION::quality_gate` findings whose evidence
    pointed into the caller's tree. Reverting either half of the fix makes this
    fail: from B, QG scored B's file (PRS 76.0, 2 errors) while claiming to
    report on A (PRS 86.0, 1 error).
    """
    a, b = tmp_path / "A", tmp_path / "B"
    for root in (a, b):
        (root / "src").mkdir(parents=True)
        (root / "src" / "mod.py").write_text(_SHARED, encoding="utf-8")
        (root / ".cathedral-keeper.json").write_text(
            json.dumps(_CK_CONFIG), encoding="utf-8")
    (b / "src" / "mod.py").write_text(_SHARED + _ONLY_IN_B_SECRET,
                                      encoding="utf-8")

    from_a = _ck_summary(a, cwd=a, out=tmp_path / "a.json")
    from_b = _ck_summary(a, cwd=b, out=tmp_path / "b.json")

    assert any(policy == "CK-INTEGRATION::quality_gate" for policy, *_ in from_a), (
        "QG did not run under CK, so this proves nothing about cwd")
    assert from_a == from_b, (
        f"same --root gave different results by cwd:\n  from A: {from_a}\n"
        f"  from B: {from_b}")
