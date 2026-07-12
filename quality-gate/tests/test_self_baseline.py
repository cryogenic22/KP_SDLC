"""E0.6 — the engine eats its own dogfood: committed baseline + ratchet.

TDD: written before .quality-gate.baseline.json and the ADR exist (RED).

Guarantees under test:
  * The committed .quality-gate.baseline.json makes `--mode check
    --baseline` exit 0 on the engine repo itself (the E0.6 unlock:
    self-CI can flip to blocking without a mass remediation).
  * ANTI-CASE (no vacuous green): a fresh error injected into a copy of
    the repo fails the same check and is named in the report — the
    baseline tolerates only the debt it recorded, never new code — and
    the check run leaves the baseline byte-identical.
  * The ADR's stated totals match the committed baseline (both are
    parsed — the ADR cannot silently drift from the artifact it
    documents).
  * Ratchet direction: the files remediated in E0.6 carry improved
    entries (reporting/__init__.py at/above the floor; the TODO/BUG
    token debt is gone), and no baseline entry is vetoed — E0.4 doctrine
    makes a veto unbaselineable, so a vetoed entry could never go green.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
QG_SCRIPT = REPO / "quality-gate" / "quality_gate.py"
BASELINE = REPO / ".quality-gate.baseline.json"
ADR = REPO / "docs" / "decisions" / "0003-qg-debt-baseline.md"

PRS_FLOOR = 85.0

# Assembled at runtime so THIS file does not trip the marker rule.
_MARK = "TO" + "DO"

# Copy-tree noise that must not be scanned in the fixture copy ("nul" is
# the Windows reserved-name artifact — unreadable, breaks copytree).
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".claude", "__pycache__", ".pytest_cache", ".quality-reports",
    "node_modules", "*.sarif", "nul",
    # Build artifacts a `pip install .` leaves in the tree (self-CI installs the
    # package before `make test`). They are not source: build/lib holds copies
    # of every module, which would double-count the fixture scan, and an
    # egg-info dir is packaging metadata. Excluding them keeps the fixture a
    # faithful copy of the SOURCE regardless of whether the tree has been built.
    "build", "dist", "*.egg-info",
)

_ADR_TOTALS_RE = re.compile(
    r"baseline-totals:\s*files=(\d+)\s+errors=(\d+)\s+warnings=(\d+)"
    r"\s+below_floor=(\d+)\s+vetoed=(\d+)"
)


def _check_cli(root: Path, baseline: Path) -> subprocess.CompletedProcess:
    """Run the exact blocking command self-CI runs (modulo --sarif).

    cwd is pinned to *root* so a git-less fixture copy scans its own tree
    (the engine falls back to cwd when the scan root has no .git).
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(QG_SCRIPT), "--root", str(root),
         "--mode", "check", "--baseline", str(baseline), "--json"],
        capture_output=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(root), timeout=600,
    )


def _baseline_files() -> dict:
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return dict(data["files"])


def test_check_mode_with_committed_baseline_is_green():
    """`--mode check --baseline` on the repo root exits 0: every scanned
    file matches (or beats) its committed entry, so tolerated debt no
    longer fails the gate."""
    assert BASELINE.exists(), (
        "missing committed .quality-gate.baseline.json — generate it locally "
        "via `python quality-gate/quality_gate.py --root . --mode baseline`"
    )
    proc = _check_cli(REPO, BASELINE)
    assert proc.returncode == 0, (
        f"check with the committed baseline exited {proc.returncode}:\n"
        f"{proc.stdout[-3000:]}\n{proc.stderr[-1000:]}"
    )
    report = json.loads(proc.stdout)
    assert report["passed"] is True
    assert report["baseline"]["status"] == "ok"
    # Anti-vacuous: the green must come from a real full scan, not an
    # empty file set or an unmatched baseline.
    assert report["stats"]["files_checked"] >= 100
    assert report["baseline"]["matched"] >= 100
    assert report["baseline"]["regressed"] == 0


def test_new_error_not_masked_by_baseline():
    """ANTI-CASE: new code faces the floor. Injecting a file with fresh
    errors into a copy of the repo flips the same check to exit 1, the
    report names the injected file, and the baseline is left untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "repo"
        shutil.copytree(REPO, dst, ignore=_COPY_IGNORE)
        baseline_copy = dst / ".quality-gate.baseline.json"
        assert baseline_copy.exists(), "fixture copy lost the baseline"

        proc0 = _check_cli(dst, baseline_copy)
        assert proc0.returncode == 0, (
            f"fixture copy must start green (sanity): {proc0.stdout[-2000:]}"
        )

        injected = dst / "znew_slop.py"
        injected.write_text(
            f"# {_MARK} fix later\n# {_MARK} and this too\nx = 1\n",
            encoding="utf-8",
        )
        before = baseline_copy.read_bytes()

        proc1 = _check_cli(dst, baseline_copy)
        assert proc1.returncode == 1, (
            "a fresh error in a new file must fail the baselined check "
            f"(got exit {proc1.returncode}) — the baseline is masking new code"
        )
        report = json.loads(proc1.stdout)
        named = [
            issue for issue in report["issues"]
            if Path(issue["file"]).name == "znew_slop.py"
            and issue["severity"] == "error"
        ]
        assert named, (
            "the failing report must name the injected file; got only "
            f"{sorted({i['file'] for i in report['issues']})[:10]}"
        )
        assert baseline_copy.read_bytes() == before, (
            "check mode rewrote the baseline — regeneration must never be a "
            "side effect of checking"
        )


def test_adr_totals_match_committed_baseline():
    """The ADR carries a machine-readable totals line that must equal the
    totals derived from the committed baseline (ADR-artifact coupling)."""
    assert ADR.exists(), "missing docs/decisions/0003-qg-debt-baseline.md"
    entries = list(_baseline_files().values())
    assert entries, "committed baseline has no file entries — vacuous"
    derived = (
        len(entries),
        sum(int(e["errors"]) for e in entries),
        sum(int(e["warnings"]) for e in entries),
        sum(1 for e in entries if float(e["prs"]) < PRS_FLOOR),
        sum(1 for e in entries if bool(e.get("vetoed"))),
    )
    match = _ADR_TOTALS_RE.search(ADR.read_text(encoding="utf-8"))
    assert match, (
        "ADR 0003 must state its numbers on a machine-readable line: "
        "'baseline-totals: files=N errors=N warnings=N below_floor=N vetoed=N'"
    )
    stated = tuple(int(g) for g in match.groups())
    assert stated == derived, (
        f"ADR states {stated} but the committed baseline derives {derived} "
        "(files, errors, warnings, below_floor, vetoed) — regenerate one of "
        "them; they must not drift apart"
    )


def test_remediated_files_ratchet_direction():
    """The E0.6 remediations are visible in the committed baseline: the
    reporting package is at/above the floor, the marker-token debt in the
    other two named files is gone, and nothing vetoed was baselined."""
    files = _baseline_files()

    rep = files.get("reporting/__init__.py")
    assert rep is None or float(rep["prs"]) >= PRS_FLOOR, (
        f"reporting/__init__.py was remediated to >= {PRS_FLOOR} but its "
        f"baseline entry says {rep}"
    )

    fixes = files.get("fix-engine/fe/fixes_additional.py")
    assert fixes is not None and int(fixes["errors"]) <= 1, (
        "fix-engine/fe/fixes_additional.py carried 3 errors (2 marker-token "
        f"comments) before E0.6; its entry must show <= 1: {fixes}"
    )

    coherence = files.get("cathedral-keeper/tests/test_coherence.py")
    assert coherence is not None and int(coherence["errors"]) == 0, (
        "cathedral-keeper/tests/test_coherence.py carried 1 marker-token "
        f"error before E0.6; its entry must show 0: {coherence}"
    )

    vetoed = sorted(k for k, v in files.items() if bool(v.get("vetoed")))
    assert not vetoed, (
        f"vetoed entries can never pass the ratchet, so committing them is "
        f"either dead weight or a masked veto: {vetoed}"
    )


def test_remediated_reporting_scores_above_floor_when_scanned():
    """Live re-scan agreement for the fully remediated file: scanning
    reporting/__init__.py today scores at/above the floor (the ratchet
    direction is real, not a stale baseline artifact)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(QG_SCRIPT), "--root", str(REPO),
         "--mode", "audit", "--json", "reporting/__init__.py"],
        capture_output=True, encoding="utf-8", errors="replace",
        env=env, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    prs = json.loads(proc.stdout)["prs"]
    assert len(prs) == 1, f"expected exactly one scored file, got {list(prs)}"
    entry = next(iter(prs.values()))
    assert float(entry["score"]) >= PRS_FLOOR, (
        f"reporting/__init__.py scans at {entry} — below the floor it was "
        "remediated to"
    )


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
