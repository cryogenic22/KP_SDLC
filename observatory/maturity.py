"""Evidence-backed capability maturity and explicit historical checkpoints."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MATURITY_SCHEMA = "agent-observatory/maturity@1"
_LEVELS = ("unobserved", "initial", "repeatable", "managed", "measured", "improving")


def _dimension(identifier: str, level: int, evidence: list[str], gaps: list[str]) -> dict[str, Any]:
    bounded = max(0, min(5, level))
    return {"id": identifier, "level": bounded, "label": _LEVELS[bounded],
            "evidence": evidence, "next_gaps": gaps}


class MaturityEngine:
    """Measure observable engineering capability, never event volume or LOC."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def evaluate(self, snapshot: dict[str, Any], telemetry: list[dict[str, Any]]) -> dict[str, Any]:
        dimensions = [
            self._observability(telemetry),
            self._memory(snapshot.get("memory") or []),
            self._governance(snapshot.get("gates") or []),
            self._evaluation(snapshot.get("gates") or []),
            self._coordination(snapshot),
        ]
        payload = {"schema": MATURITY_SCHEMA, "dimensions": dimensions}
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]
        history = self.history()
        previous = history[-1] if history else None
        deltas = {}
        if previous:
            old = {item["id"]: item["level"] for item in previous.get("dimensions", [])}
            deltas = {item["id"]: item["level"] - old.get(item["id"], item["level"])
                      for item in dimensions}
        payload.update({
            "fingerprint": fingerprint,
            "recorded_checkpoints": len(history),
            "delta_from_last_checkpoint": deltas,
            "improved_dimensions": sorted(name for name, delta in deltas.items() if delta > 0),
            "regressed_dimensions": sorted(name for name, delta in deltas.items() if delta < 0),
        })
        return payload

    def record(self, assessment: dict[str, Any]) -> tuple[Path, bool]:
        target = self.root / ".observatory" / "maturity-history.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        history = self.history()
        if history and history[-1].get("fingerprint") == assessment.get("fingerprint"):
            return target, False
        record = dict(assessment)
        record["recorded_at"] = datetime.now(timezone.utc).isoformat()
        data = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, data.encode("utf-8"))
        finally:
            os.close(descriptor)
        return target, True

    def history(self) -> list[dict[str, Any]]:
        path = self.root / ".observatory" / "maturity-history.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        values = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("schema") == MATURITY_SCHEMA:
                values.append(value)
        return values

    @staticmethod
    def _observability(reports):
        capabilities = [report.get("capabilities") or {} for report in reports if report.get("detected")]
        evidence = []
        if capabilities:
            evidence.append("at least one harness telemetry adapter detected")
        names = ("session_lifecycle", "tool_lifecycle", "permissions", "subagents", "compaction")
        covered = sum(any(capability.get(name) for capability in capabilities) for name in names)
        evidence.extend(f"canonical capability: {name}" for name in names
                        if any(capability.get(name) for capability in capabilities))
        live = any(capability.get("live_events_observed") for capability in capabilities)
        level = 0 if not capabilities else 1 + min(3, covered // 2) + (1 if live else 0)
        gaps = [name for name in names if not any(capability.get(name) for capability in capabilities)]
        if not live:
            gaps.append("observe a live event stream, not configuration alone")
        return _dimension("observability", level, evidence, gaps)

    @staticmethod
    def _memory(assessments):
        if not assessments:
            return _dimension("memory", 0, [], ["install or declare a memory adapter"])
        capabilities = assessments[0].get("capabilities") or {}
        names = ("checkpoint_capture", "compaction_capture", "session_injection",
                 "session_finalization", "structured_recall")
        covered = sum(bool(capabilities.get(name)) for name in names)
        usage = assessments[0].get("usage") or {}
        used_well = int(usage.get("ledger_reads") or 0) >= int(usage.get("transcript_greps") or 0)
        level = min(4, covered) + (1 if covered == len(names) and used_well else 0)
        evidence = [f"memory capability: {name}" for name in names if capabilities.get(name)]
        gaps = [name for name in names if not capabilities.get(name)]
        if not used_well:
            gaps.append("prefer structured recall over raw transcript fallback")
        return _dimension("memory", level, evidence, gaps)

    @staticmethod
    def _governance(gates):
        by_id = {gate["id"]: gate for gate in gates}
        quality = by_id.get("quality", {})
        architecture = by_id.get("architecture", {})
        q_present = quality.get("status") not in {None, "missing"}
        q_nonvacuous = int(quality.get("files_checked") or 0) > 0
        # A real architecture verdict (pass/fail) is evidence; a missing or vacuous
        # (inconclusive) report is not, so it earns no governance level.
        a_present = architecture.get("status") in {"pass", "fail"}
        level = int(q_present) + int(q_nonvacuous) + int(a_present)
        if q_nonvacuous and architecture.get("status") == "pass":
            level += 1
        evidence = (["quality artifact present"] if q_present else []) + \
                   (["quality artifact is non-vacuous"] if q_nonvacuous else []) + \
                   (["architecture artifact present"] if a_present else [])
        gaps = []
        if not q_nonvacuous:
            gaps.append("produce a current quality result checking at least one file")
        if not a_present:
            gaps.append("produce architecture-governance evidence")
        if architecture.get("status") == "fail":
            gaps.append("resolve or explicitly baseline high architecture findings")
        return _dimension("quality_governance", level, evidence, gaps)

    @staticmethod
    def _evaluation(gates):
        evaluation = next((gate for gate in gates if gate.get("id") == "eval"), {})
        status = evaluation.get("status")
        if status == "missing":
            return _dimension("evaluation", 0, [], ["publish a non-vacuous eval scorecard"])
        total = int(evaluation.get("total") or 0)
        level = 2 if total > 0 else 1
        if status == "pass":
            level = 4
        gaps = [] if status == "pass" else ["make relevant acceptance evaluations pass"]
        return _dimension("evaluation", level, [f"eval artifact status: {status}", f"cases: {total}"], gaps)

    @staticmethod
    def _coordination(snapshot):
        worktrees = snapshot.get("worktrees") or []
        events = int((snapshot.get("summary") or {}).get("events_observed") or 0)
        active = sum(bool(tree.get("observed_active")) for tree in worktrees)
        level = 1 if worktrees else 0
        if worktrees and events:
            level = 2
        if active:
            level = 3
        gaps = ["correlate agents to worktrees and tasks"] if worktrees and not active else []
        gaps.append("add overlapping-file and merge-risk evidence")
        return _dimension("parallel_coordination", level,
                          [f"worktrees inventoried: {len(worktrees)}", f"observed active: {active}"], gaps)

