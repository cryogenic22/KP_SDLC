"""FEAT-002 — Tool Status Sentinel.

Every QG/CK run emits a structured tool_status object as the first key
in JSON output. Includes a heartbeat test that evaluates a known-bad
snippet to verify the rule engine is functioning.

If the heartbeat fails (0 findings on known-bad input), status="crashed".
CI should fail on status != "ok" when --require-healthy is set.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


@dataclass(slots=True)
class ToolStatus:
    """Structured status of a tool run."""

    status: str                  # "ok" | "degraded" | "crashed"
    components_run: List[str]
    components_failed: List[str]
    heartbeat_passed: bool
    run_id: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "components_run": list(self.components_run),
            "components_failed": list(self.components_failed),
            "heartbeat_passed": self.heartbeat_passed,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
        }


def build_tool_status(
    *,
    components_run: List[str],
    components_failed: List[str],
    heartbeat_passed: bool,
) -> ToolStatus:
    """Build a ToolStatus from run results.

    Status logic:
    - crashed: heartbeat failed (rule engine is broken)
    - degraded: some components failed but heartbeat passed
    - ok: everything passed
    """
    if not heartbeat_passed:
        status = "crashed"
    elif components_failed:
        status = "degraded"
    else:
        status = "ok"

    return ToolStatus(
        status=status,
        components_run=components_run,
        components_failed=components_failed,
        heartbeat_passed=heartbeat_passed,
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Heartbeat ────────────────────────────────────────────────────────

# Known-bad snippet that MUST produce at least 2 findings.
# If it produces 0, the rule engine is broken.
_HEARTBEAT_SNIPPET = '''
password = "hunter2"
def very_long_function_name():
    x = 1; y = 2; z = 3; a = 4; b = 5; c = 6; d = 7; e = 8
    x = 1; y = 2; z = 3; a = 4; b = 5; c = 6; d = 7; e = 8
    x = 1; y = 2; z = 3; a = 4; b = 5; c = 6; d = 7; e = 8
    x = 1; y = 2; z = 3; a = 4; b = 5; c = 6; d = 7; e = 8
    import os; os.system(input())
    try:
        risky()
    except:
        pass
    return x
'''

# Expected findings on the heartbeat snippet:
# 1. no_hardcoded_secrets: password = "hunter2"
# 2. no_silent_catch: except: pass


def run_heartbeat() -> Tuple[bool, int]:
    """Run the heartbeat test against a known-bad snippet.

    Returns:
        (passed, finding_count) — passed=True if >= 2 findings detected.
    """
    import tempfile
    import os
    from pathlib import Path

    # Write snippet to temp file
    fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="qg_heartbeat_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(_HEARTBEAT_SNIPPET)

        # Import QG and run on the snippet
        import sys
        qg_dir = str(Path(__file__).resolve().parents[1])
        if qg_dir not in sys.path:
            sys.path.insert(0, qg_dir)

        from quality_gate import QualityGate

        qg = QualityGate(root_dir=str(Path(tmp_path).parent), quiet=True)
        result = qg.run(paths=[tmp_path])

        finding_count = len(result.issues)
        passed = finding_count >= 2

        return passed, finding_count
    except Exception:
        return False, 0
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
