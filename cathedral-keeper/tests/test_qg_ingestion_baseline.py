"""E0.6 — CK's QG ingestion is baseline-aware (no double-gating of debt).

TDD: written before the baseline-aware ingestion exists (RED).

Guarantees under test:
  * A file whose QG counts are within its committed-baseline entry
    ingests at LOW severity: CK stops re-flagging, at high, the exact
    debt the QG ratchet already tolerates (the double-gate that kept
    `ck analyze` red after QG went green).
  * A REGRESSED file (counts above its entry) stays HIGH — the two
    gates agree on what a regression is.
  * A file absent from the baseline keeps today's severity (new code
    faces the full gate in both tools).
  * ANTI-CASE (fail open, toward strictness): a corrupt or missing
    baseline restores the pre-E0.6 behavior (high) — a broken baseline
    makes CK stricter, never quieter.
  * A vetoed file is never downgraded — mirrors QG doctrine that a
    baseline never masks a security veto.
  * With the committed baseline, `ck analyze --mode repo` on this repo
    exits 0 — the exit code ENGINE_PROFILE's CK_BLOCKING=True relies on.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.integrations.quality_gate import run_quality_gate
from cathedral_keeper.integrations.types import IntegrationContext

REPO = Path(__file__).resolve().parents[2]
CK_SCRIPT = REPO / "cathedral-keeper" / "ck.py"

_QG_REL = "quality-gate/quality_gate.py"


def _ctx(root: Path) -> IntegrationContext:
    """IntegrationContext rooted at a tmp dir with a real (stub) QG script,
    so run_quality_gate takes its normal path and only the subprocess call
    is patched."""
    stub = root / "quality-gate" / "quality_gate.py"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("# stub - the subprocess call is patched in tests\n",
                    encoding="utf-8")
    paths_file = root / "paths.txt"
    paths_file.write_text("app.py\n", encoding="utf-8")
    return IntegrationContext(
        root=root, target_paths_file=paths_file, target_rel_paths=["app.py"],
    )


def _payload(*, score: float, errors: int, warnings: int,
             vetoed: bool = False) -> dict:
    return {
        "prs": {
            "app.py": {
                "score": score, "errors": errors, "warnings": warnings,
                "vetoed": vetoed,
            },
        },
        "issues": [
            {"file": "app.py", "line": 3, "rule": "function_size",
             "message": "Function too long."},
        ],
    }


def _write_baseline(root: Path, entry: dict) -> None:
    data = {
        "version": 1,
        "generated_by": "quality-gate baseline",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "commit": "unknown",
        "min_score": 85,
        "files": {"app.py": entry},
    }
    (root / ".quality-gate.baseline.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8",
    )


def _ingest(root: Path, payload: dict) -> list:
    ctx = _ctx(root)
    target = "cathedral_keeper.integrations.quality_gate._run_quality_gate_json"
    with patch(target) as mock_run:
        mock_run.return_value = (payload, None)
        return run_quality_gate(ctx, {"qg_path": _QG_REL})


def _single(findings: list):
    assert len(findings) == 1, (
        f"expected exactly one ingested finding, got "
        f"{[(f.policy_id, f.severity) for f in findings]}"
    )
    return findings[0]


def test_baselined_debt_ingests_low():
    """Counts within the baseline entry -> severity 'low' (tolerated debt)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_baseline(root, {"prs": 46.0, "errors": 3, "warnings": 12,
                               "vetoed": False})
        finding = _single(_ingest(root, _payload(score=46.0, errors=3,
                                                 warnings=12)))
        assert finding.severity == "low", (
            f"baselined, non-regressed debt must ingest low, got "
            f"{finding.severity!r}"
        )
        assert finding.metadata.get("baselined") is True


def test_regressed_file_stays_high():
    """Counts above the baseline entry -> the downgrade must NOT apply."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_baseline(root, {"prs": 56.0, "errors": 2, "warnings": 12,
                               "vetoed": False})
        finding = _single(_ingest(root, _payload(score=46.0, errors=3,
                                                 warnings=12)))
        assert finding.severity == "high", (
            "a file regressed beyond its baseline entry must stay high, got "
            f"{finding.severity!r}"
        )
        assert finding.metadata.get("baselined") is not True


def test_new_file_not_in_baseline_stays_high():
    """No baseline entry -> new code keeps the pre-E0.6 severity."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_baseline(root, {"prs": 90.0, "errors": 0, "warnings": 5,
                               "vetoed": False})
        payload = {
            "prs": {"other.py": {"score": 46.0, "errors": 3, "warnings": 12,
                                 "vetoed": False}},
            "issues": [],
        }
        finding = _single(_ingest(root, payload))
        assert finding.severity == "high"


def test_corrupt_baseline_fails_open_to_high():
    """ANTI-CASE: unparseable baseline -> pre-E0.6 behavior (high), never a
    silent downgrade riding a broken file."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".quality-gate.baseline.json").write_text(
            "{ this is not json", encoding="utf-8",
        )
        finding = _single(_ingest(root, _payload(score=46.0, errors=3,
                                                 warnings=12)))
        assert finding.severity == "high", (
            f"corrupt baseline must fail open to high, got "
            f"{finding.severity!r}"
        )


def test_missing_baseline_keeps_high():
    """No baseline file at all -> pre-E0.6 behavior (high)."""
    with tempfile.TemporaryDirectory() as tmp:
        finding = _single(_ingest(Path(tmp), _payload(score=46.0, errors=3,
                                                      warnings=12)))
        assert finding.severity == "high"


def test_vetoed_file_never_downgraded():
    """A vetoed file stays high even with a matching baseline entry —
    mirrors QG: a baseline never masks a security veto."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_baseline(root, {"prs": 0.0, "errors": 1, "warnings": 0,
                               "vetoed": True})
        finding = _single(_ingest(root, _payload(score=0.0, errors=1,
                                                 warnings=0, vetoed=True)))
        assert finding.severity == "high", (
            f"vetoed file must never ingest low, got {finding.severity!r}"
        )


def test_repo_ck_analyze_exits_zero_with_committed_baseline():
    """`ck analyze --mode repo` on this repo exits 0 once QG's baselined
    debt ingests low — the honest ground for CK_BLOCKING=True in self-CI."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        out_json = out_dir / "ck-report.json"
        proc = subprocess.run(
            [sys.executable, str(CK_SCRIPT), "analyze",
             "--root", str(REPO), "--mode", "repo",
             "--out-md", str(out_dir / "ck-report.md"),
             "--out-json", str(out_json)],
            capture_output=True, encoding="utf-8", errors="replace",
            env=env, timeout=600,
        )
        assert proc.returncode == 0, (
            f"ck analyze exited {proc.returncode} — self-CI's blocking CK "
            f"step would be red:\n{proc.stdout[-2000:]}\n{proc.stderr[-1000:]}"
        )
        report = json.loads(out_json.read_text(encoding="utf-8"))
        findings = list(report.get("findings", []))
        # Anti-vacuous: exit 0 must mean "nothing at/above high", not
        # "nothing was analyzed".
        assert findings, "ck analyze reported zero findings on this repo"
        highs = [f for f in findings
                 if str(f.get("severity")) in ("high", "blocker", "critical")]
        assert not highs, (
            f"exit 0 with high findings would be a broken threshold: "
            f"{[(f.get('policy_id'), f.get('title')) for f in highs[:5]]}"
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
