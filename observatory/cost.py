"""Token-cost attribution — the Observatory's first consumer of real spend.

Capture has been running with no accounting: `duration_ms` is recorded and read
by nothing, and no token, step or spend figure exists anywhere in the repo. Every
efficiency claim about the harness is therefore unfalsifiable. This module makes
the numbers exist.

Token counts live only in the Claude Code session transcript — hook events carry
none (``events._SAFE_FIELDS`` has neither a usage field nor ``transcript_path``),
so the meter locates transcripts itself and reports three-state when it cannot.

**Content-blind by construction (I1).** The extractor reads numeric usage fields,
message role/type, and tool *names*. It never reads a ``tool_use`` block's
``input``, never reads assistant text, and measures tool results by length only —
the bytes are counted and discarded. Privacy here is a property of what the code
physically holds, not of filtering applied afterwards; the leak scan in
:func:`scan_forbidden` is the anti-case that proves it, not the mechanism.

The emitted record keeps real session ids, matching the posture of the adjacent
``.observatory/events.jsonl`` (machine-local, gitignored, mode 0600). The
sanitized cross-repo export that opaquifies them is a later loop.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .events import append_jsonl

logger = logging.getLogger("observatory_cost")

COST_SCHEMA = "agent-observatory/cost@1"

_HISTORY_NAME = "cost-history.jsonl"

# Absolute paths must never reach the record. Session ids are permitted here by
# design (see module docstring), so they are deliberately absent from this list.
_FORBIDDEN = (
    ("windows_abs_path", re.compile(r"[A-Za-z]:[\\/]")),
    ("unix_home_path", re.compile(r"/(?:Users|home)/")),
)


def scan_forbidden(text: str) -> list[str]:
    """Names of forbidden patterns present in ``text`` (empty when clean)."""
    return sorted({name for name, pattern in _FORBIDDEN if pattern.search(text)})


def transcript_dir_for(root: Path, projects_root: Path | None = None) -> Path:
    """Claude Code stores a repo's transcripts under a slug of its absolute
    path, every non-alphanumeric character replaced by a dash."""
    base = projects_root or (Path.home() / ".claude" / "projects")
    return base / re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))


@dataclass
class SessionTally:
    session_id: str
    steps: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    tool_calls: int = 0
    text_only_steps: int = 0
    tool_result_bytes: int = 0
    tools: Counter = field(default_factory=Counter)
    first_timestamp: str = ""
    last_timestamp: str = ""


def _add_usage(tally: SessionTally, usage: dict) -> None:
    tally.steps += 1
    tally.input += int(usage.get("input_tokens") or 0)
    tally.output += int(usage.get("output_tokens") or 0)
    tally.cache_read += int(usage.get("cache_read_input_tokens") or 0)
    tally.cache_write += int(usage.get("cache_creation_input_tokens") or 0)


def _tool_names(message: dict) -> list[str]:
    """Tool NAMES only. A ``tool_use`` block's ``input`` holds commands, prompts
    and file content, and is never read."""
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [str(block.get("name") or "unknown") for block in content
            if isinstance(block, dict) and block.get("type") == "tool_use"]


def _result_bytes(message: dict) -> int:
    """Size of tool results. The content is measured and discarded — it is never
    stored on the tally and never reaches the record."""
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    sizes = [len(json.dumps(block.get("content") or "")) for block in content
             if isinstance(block, dict) and block.get("type") == "tool_result"]
    return sum(sizes)


def _message_of(record: dict) -> dict | None:
    message = record.get("message")
    return message if isinstance(message, dict) else None


def _ingest_assistant(tally: SessionTally, message: dict) -> None:
    usage = message.get("usage")
    billed = isinstance(usage, dict)
    if billed:
        _add_usage(tally, usage)
    names = _tool_names(message)
    tally.tool_calls += len(names)
    tally.tools.update(names)
    if billed and not names:
        # A billed step that carried no tool call: narration, priced at a full
        # context read like any other step.
        tally.text_only_steps += 1


def _ingest(tally: SessionTally, record: dict) -> None:
    timestamp = str(record.get("timestamp") or "")
    if timestamp:
        tally.first_timestamp = tally.first_timestamp or timestamp
        tally.last_timestamp = timestamp
    message = _message_of(record)
    if message is None:
        return
    kind = record.get("type")
    if kind == "assistant":
        _ingest_assistant(tally, message)
    elif kind == "user":
        tally.tool_result_bytes += _result_bytes(message)


def read_transcript(path: Path) -> SessionTally:
    """Tally one session transcript. Unreadable or malformed lines are skipped
    rather than aborting the run — a torn line must not lose the whole session."""
    tally = SessionTally(session_id=path.stem)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                _ingest_line(tally, line)
    except OSError as exc:
        logger.warning("observatory cost: unreadable transcript %s: %s", path, exc)
    return tally


def _ingest_line(tally: SessionTally, line: str) -> None:
    try:
        record = json.loads(line)
    except ValueError:
        return
    if isinstance(record, dict):
        _ingest(tally, record)


def tally_to_dict(tally: SessionTally) -> dict:
    total_input = tally.input + tally.cache_read + tally.cache_write
    steps = tally.steps
    return {
        "session_id": tally.session_id,
        "steps": steps,
        "input": tally.input,
        "output": tally.output,
        "cache_read": tally.cache_read,
        "cache_write": tally.cache_write,
        "total_input": total_input,
        # None, not 0: a session with no billed step has no cost-per-step, and a
        # zero here would read as "free".
        "cost_per_step": round(total_input / steps, 1) if steps else None,
        "tool_calls": tally.tool_calls,
        "text_only_steps": tally.text_only_steps,
        "tool_result_bytes": tally.tool_result_bytes,
        "tools": dict(sorted(tally.tools.items())),
        "first_timestamp": tally.first_timestamp,
        "last_timestamp": tally.last_timestamp,
    }


_SUMMED = ("steps", "input", "output", "cache_read", "cache_write",
           "total_input", "tool_calls", "text_only_steps", "tool_result_bytes")


def _totals(sessions: list[dict]) -> dict:
    totals = {name: sum(int(s[name]) for s in sessions) for name in _SUMMED}
    steps = totals["steps"]
    totals["sessions"] = len(sessions)
    totals["cost_per_step"] = (round(totals["total_input"] / steps, 1)
                               if steps else None)
    # The headline comparison: tool output is ~4 bytes/token, so this shows
    # whether spend tracks what tools returned or simply how many steps ran.
    totals["tool_result_tokens_approx"] = totals["tool_result_bytes"] // 4
    return totals


def _unavailable(root: Path, reason: str) -> dict:
    return {"schema": COST_SCHEMA, "repo": root.name, "available": False,
            "reason": reason, "sessions": [], "totals": {}}


def _transcript_paths(directory: Path, limit: int | None) -> list[Path]:
    paths = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    return paths[:limit] if limit else paths


def measure(root: Path, *, projects_root: Path | None = None,
            limit: int | None = None) -> dict:
    """Attribute token cost per session for ``root``. Returns three-state: an
    absent transcript directory yields ``available: false`` with a reason, never
    zeros that would read as 'this was cheap'."""
    directory = transcript_dir_for(root, projects_root)
    if not directory.is_dir():
        return _unavailable(root, "no transcript directory for this repo; token "
                                  "counts exist only in session transcripts, "
                                  "which hook events do not carry")
    paths = _transcript_paths(directory, limit)
    if not paths:
        return _unavailable(root, "transcript directory is empty")
    sessions = [tally_to_dict(read_transcript(path)) for path in paths]
    return {"schema": COST_SCHEMA, "repo": root.name, "available": True,
            "sessions": sessions, "totals": _totals(sessions)}


def record(root: Path, report: dict) -> Path:
    """Append the report's totals to the local cost ledger. Refuses to write if
    the payload carries a forbidden pattern (I3) — fail closed."""
    payload = {"schema": COST_SCHEMA, "repo": report.get("repo"),
               "totals": report.get("totals") or {},
               "sessions": len(report.get("sessions") or [])}
    leaks = scan_forbidden(json.dumps(payload))
    if leaks:
        raise ValueError(
            f"refusing to write the cost ledger: payload carries {leaks}")
    return append_jsonl(root.resolve() / ".observatory" / _HISTORY_NAME, payload)


def _session_lines(report: dict) -> list[str]:
    lines = []
    for session in report["sessions"]:
        per_step = session["cost_per_step"]
        lines.append(f"  {session['session_id'][:8]}  steps={session['steps']:>5}  "
                     f"in={session['total_input']:>13,}  out={session['output']:>9,}  "
                     f"per_step={per_step if per_step is not None else 'n/a':>10}")
    return lines


def report_lines(report: dict) -> list[str]:
    if not report.get("available"):
        return [f"[observatory cost] {report['repo']}: UNAVAILABLE — "
                f"{report.get('reason')}"]
    totals = report["totals"]
    lines = [f"[observatory cost] {report['repo']}: {totals['sessions']} session(s)"]
    lines += _session_lines(report)
    lines.append(f"  TOTAL  steps={totals['steps']:,}  "
                 f"input={totals['total_input']:,}  output={totals['output']:,}  "
                 f"per_step={totals['cost_per_step']:,}")
    lines.append(f"  tool results: {totals['tool_result_bytes']:,} bytes "
                 f"(~{totals['tool_result_tokens_approx']:,} tokens, "
                 f"{_share(totals)} of input) | "
                 f"narration steps: {totals['text_only_steps']:,}")
    return lines


def _share(totals: dict) -> str:
    total_input = totals["total_input"]
    if not total_input:
        return "n/a"
    return f"{100.0 * totals['tool_result_tokens_approx'] / total_input:.2f}%"


def run(root: Path, *, as_json: bool = False, do_record: bool = False,
        limit: int | None = None, projects_root: Path | None = None) -> int:
    report = measure(root, projects_root=projects_root, limit=limit)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for line in report_lines(report):
            print(line)
    if do_record and report.get("available"):
        print(f"[observatory cost] recorded: {record(root, report)}")
    return 0 if report.get("available") else 2
