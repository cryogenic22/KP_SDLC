"""Phase 1 — Tests for QG integration silent-failure fix.

TDD: Verifies that CK's QG integration correctly distinguishes
"no findings" from "QG crashed" — the exact bug from CtxPack
where rate-limited API calls were silently scored as failures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.integrations.quality_gate import (
    _run_quality_gate_json,
    run_quality_gate,
)
from cathedral_keeper.integrations.types import IntegrationContext
from cathedral_keeper.models import Finding


def _make_ctx(tmp_path: Path = None) -> IntegrationContext:
    """Create a minimal IntegrationContext for testing."""
    root = tmp_path or Path(".")
    return IntegrationContext(
        root=root.resolve(),
        target_paths_file=root / "paths.txt",
        target_rel_paths=["src/app.py"],
    )


# ── _run_quality_gate_json tests ─────────────────────────────────────


def test_qg_json_valid_output():
    """Valid QG JSON output should return (payload, None)."""
    valid_output = json.dumps({"prs": {"app.py": {"score": 92}}, "issues": []})

    with patch("cathedral_keeper.integrations.quality_gate.retry_call") as mock_retry:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = valid_output.encode("utf-8")
        mock_proc.stderr = b""
        mock_retry.return_value = mock_proc

        payload, error = _run_quality_gate_json(
            root=Path("."), qg=Path("qg.py"), paths_file=Path("paths.txt"),
        )
        assert error is None
        assert payload["prs"]["app.py"]["score"] == 92


def test_qg_json_crash_returncode():
    """QG crash (returncode=2) should return error_info, not empty dict."""
    with patch("cathedral_keeper.integrations.quality_gate.retry_call") as mock_retry:
        mock_proc = MagicMock()
        mock_proc.returncode = 2
        mock_proc.stdout = b""
        mock_proc.stderr = b"Traceback: SyntaxError"
        mock_retry.return_value = mock_proc

        payload, error = _run_quality_gate_json(
            root=Path("."), qg=Path("qg.py"), paths_file=Path("paths.txt"),
        )
        assert error is not None
        assert "code 2" in error
        assert payload == {}


def test_qg_json_invalid_json():
    """Invalid JSON from QG should return error_info, not empty dict."""
    with patch("cathedral_keeper.integrations.quality_gate.retry_call") as mock_retry:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b"not valid json {{{{"
        mock_proc.stderr = b""
        mock_retry.return_value = mock_proc

        payload, error = _run_quality_gate_json(
            root=Path("."), qg=Path("qg.py"), paths_file=Path("paths.txt"),
        )
        assert error is not None
        assert "not valid JSON" in error
        assert payload == {}


def test_qg_json_retry_failure():
    """If retry_call returns RetryFailure, should return error_info."""
    from cathedral_keeper.retry import RetryFailure

    with patch("cathedral_keeper.integrations.quality_gate.retry_call") as mock_retry:
        mock_retry.return_value = RetryFailure(attempts=2, last_error="OSError: timeout")

        payload, error = _run_quality_gate_json(
            root=Path("."), qg=Path("qg.py"), paths_file=Path("paths.txt"),
        )
        assert error is not None
        assert "Retry exhausted" in error
        assert payload == {}


def test_qg_json_empty_stdout_pass():
    """QG with returncode=0 but empty stdout = genuinely no files."""
    with patch("cathedral_keeper.integrations.quality_gate.retry_call") as mock_retry:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        mock_retry.return_value = mock_proc

        payload, error = _run_quality_gate_json(
            root=Path("."), qg=Path("qg.py"), paths_file=Path("paths.txt"),
        )
        assert error is None  # Not an error — genuinely empty
        assert payload == {}


# ── run_quality_gate tests ───────────────────────────────────────────


def test_run_qg_emits_finding_on_script_not_found():
    """If QG script doesn't exist, emit info finding (not silent skip)."""
    ctx = _make_ctx()
    cfg = {"qg_path": "nonexistent/quality_gate.py"}
    findings = run_quality_gate(ctx, cfg)

    assert len(findings) == 1
    assert findings[0].policy_id == "CK-INTEGRATION::quality_gate"
    assert findings[0].severity == "info"
    assert "not found" in findings[0].title.lower()


def test_run_qg_emits_finding_on_execution_failure():
    """If QG crashes, emit medium-severity finding with error details."""
    ctx = _make_ctx()
    cfg = {"qg_path": "quality_gate.py"}

    with patch("cathedral_keeper.integrations.quality_gate._run_quality_gate_json") as mock_run:
        mock_run.return_value = ({}, "QG exited with code 2. stderr: SyntaxError")

        # Also need to mock the path existence check
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.resolve", return_value=Path("/fake/quality_gate.py")):
                findings = run_quality_gate(ctx, cfg)

    assert len(findings) == 1
    f = findings[0]
    assert f.policy_id == "CK-INTEGRATION::quality_gate"
    assert f.severity == "medium"
    assert "failed to execute" in f.title.lower()
    assert f.metadata["status"] == "execution_failed"


def test_run_qg_passes_valid_payload():
    """Valid QG output should produce PRS findings normally."""
    ctx = _make_ctx()
    cfg = {"qg_path": "quality_gate.py"}

    payload = {
        "prs": {"src/app.py": {"score": 72.0, "errors": 2, "warnings": 4}},
        "issues": [
            {"file": "src/app.py", "line": 10, "rule": "file_size", "message": "too big"},
        ],
    }

    with patch("cathedral_keeper.integrations.quality_gate._run_quality_gate_json") as mock_run:
        mock_run.return_value = (payload, None)
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.resolve", return_value=Path("/fake/quality_gate.py")):
                findings = run_quality_gate(ctx, cfg)

    # Should produce a PRS finding for app.py (score 72 < 85)
    assert len(findings) >= 1
    assert any(f.metadata.get("prs") == 72.0 for f in findings)


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
