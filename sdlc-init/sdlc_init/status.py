"""`sdlc status` — the integrity-drift reader for a born-gated repo.

`sdlc init` has always RECORDED what a repo received: engine SHA, engine
version, and a per-file sha256 of the vendored `tools/qa/` tree, all in
`.harness/manifest.json`. Nothing ever read that record back. A born repo
therefore could not answer either question that matters after birth:

  integrity — is the vendored engine I am running still the bytes that were
              installed, or has someone edited it in place? Needs only the
              repo, so CI can run it on every push.
  upstream  — is the snapshot I was born with still current, or am I running
              a stale engine? Needs an engine checkout to compare against,
              so it is opt-in via --engine-root.

Three-state, and `unknown` never reads as `ok`. The distinction that keeps
this usable: a check that was ASKED for and could not run is `unknown` and
exits non-zero (a check that cannot run must not report green); a check that
was NOT asked for is `not_checked` and is excluded from the verdict. Without
that split, running `sdlc status` inside a born repo — which legitimately has
no engine checkout — would be permanently non-zero and trained into noise.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import harness_map as hm
from .manifest import SCHEMA as MANIFEST_SCHEMA
from .manifest import engine_sha, engine_version, vendored_record
from .vendor import hash_engine_sources, hash_installed, missing_vendor_sources

logger = logging.getLogger("sdlc_status")

SCHEMA = "sdlc-init/status@1"

OK = "ok"
DRIFT = "drift"
UNKNOWN = "unknown"
NOT_CHECKED = "not_checked"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_UNKNOWN = 2

EXIT_FOR = {OK: EXIT_OK, DRIFT: EXIT_DRIFT, UNKNOWN: EXIT_UNKNOWN}

_MANIFEST_REL = ".harness/manifest.json"
_MAX_LISTED = 10

# Plain constant, not an inline f-string: this is prose, and QG's SQL-injection
# heuristic flags long interpolated strings containing verbs like "update".
_STALE_HINT = (
    "This repo is running a stale {dest}/ snapshot. Re-running `sdlc init` "
    "will NOT refresh it (existing files are skipped by design) — the vendored "
    "files must be replaced and the manifest re-recorded."
)


def load_manifest(target: Path) -> dict | None:
    """The init record, or None if this is not a born-gated repo / it is
    unreadable. Unreadable is deliberately indistinguishable from absent:
    both mean 'nothing to verify against', and both must fail closed."""
    path = target / _MANIFEST_REL
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sdlc status: no readable manifest at %s: %s", path, exc)
        return None
    if not isinstance(manifest, dict):
        logger.warning("sdlc status: manifest root at %s is not an object", path)
        return None
    return manifest


def _unknown(reason: str) -> dict:
    return {"verdict": UNKNOWN, "reason": reason}


def _validated_record(record: object) -> tuple[dict | None,
                                               dict[str, str] | None,
                                               str | None]:
    """Validate the untrusted manifest boundary once for both status axes."""
    if not isinstance(record, dict) or not record:
        return None, None, "manifest has no engine.vendored record"
    raw_files = record.get("files")
    if not isinstance(raw_files, dict) or not all(
            isinstance(rel, str) and isinstance(digest, str)
            for rel, digest in raw_files.items()):
        return None, None, "engine.vendored record has a malformed files map"
    if not raw_files or not isinstance(record.get("sha256"), str) \
            or not record["sha256"]:
        return None, None, "engine.vendored record is incomplete (no files/sha256 map)"
    return record, dict(raw_files), None


def _record_is_self_consistent(record: dict, files: dict[str, str]) -> bool:
    """The aggregate must digest the per-file map it ships with. A mismatch
    means the record is internally inconsistent, such as after a partial
    manual edit."""
    return vendored_record(files)["sha256"] == record.get("sha256")


def check_integrity(target: Path, record: object) -> dict:
    """Vendored bytes on disk vs. the bytes init recorded."""
    record, files, problem = _validated_record(record)
    if problem:
        return _unknown(problem)
    assert record is not None and files is not None
    checked = len(files)
    if not _record_is_self_consistent(record, files):
        return {"verdict": DRIFT, "checked": checked,
                "reason": "engine.vendored.sha256 does not digest its own files map "
                          "— the manifest was edited by hand",
                "modified": [], "missing": [], "extra": []}
    try:
        disk = hash_installed(target)
    except OSError as exc:
        logger.warning("sdlc status: unreadable vendored files at %s: %s", target, exc)
        return _unknown(f"could not read vendored files: {exc}")
    recorded_keys, disk_keys = set(files), set(disk)
    modified = sorted(rel for rel in recorded_keys & disk_keys
                      if disk[rel] != files[rel])
    missing = sorted(recorded_keys - disk_keys)
    extra = sorted(disk_keys - recorded_keys)
    verdict = DRIFT if (modified or missing or extra) else OK
    return {"verdict": verdict, "checked": checked, "modified": modified,
            "missing": missing, "extra": extra}


def _diff_upstream(recorded: dict[str, str], current: dict[str, str],
                   engine_root: Path) -> dict:
    recorded_keys, current_keys = set(recorded), set(current)
    changed = sorted(rel for rel in recorded_keys & current_keys
                     if current[rel] != recorded[rel])
    added = sorted(current_keys - recorded_keys)
    removed = sorted(recorded_keys - current_keys)
    verdict = DRIFT if (changed or added or removed) else OK
    return {"verdict": verdict, "compared": len(current), "changed": changed,
            "added": added, "removed": removed,
            "engine_sha": engine_sha(engine_root),
            "engine_version": engine_version(engine_root)}


def check_upstream(engine_root: Path | None, record: object) -> dict:
    """The recorded snapshot vs. what the engine ships today."""
    if engine_root is None:
        return {"verdict": NOT_CHECKED,
                "reason": "no --engine-root given; staleness was not evaluated"}
    _record, files, problem = _validated_record(record)
    if problem:
        return _unknown(problem)
    assert files is not None
    absent = missing_vendor_sources(engine_root)
    if absent:
        return _unknown("--engine-root is not a usable engine checkout "
                        f"(missing: {', '.join(absent[:3])})")
    try:
        current = hash_engine_sources(engine_root)
    except OSError as exc:
        logger.warning("sdlc status: unreadable engine sources at %s: %s",
                       engine_root, exc)
        return _unknown(f"could not read engine sources: {exc}")
    return _diff_upstream(files, current, engine_root)


def _overall(*verdicts: str) -> str:
    """DRIFT dominates (it is actionable and certain); UNKNOWN beats OK (an
    attempted check that could not run must never aggregate to green)."""
    if DRIFT in verdicts:
        return DRIFT
    return UNKNOWN if UNKNOWN in verdicts else OK


def _no_manifest_report(target: Path) -> dict:
    blocked = _unknown("no manifest")
    return {"schema": SCHEMA, "target": target.as_posix(), "verdict": UNKNOWN,
            "exit_code": EXIT_UNKNOWN,
            "reason": f"no readable {_MANIFEST_REL} — not a born-gated repo",
            "integrity": blocked, "upstream": dict(blocked)}


def _manifest_summary(manifest: dict) -> dict:
    engine = manifest.get("engine")
    if not isinstance(engine, dict):
        engine = {}
    return {"schema": manifest.get("schema"),
            "init_status": manifest.get("status"),
            "project_name": manifest.get("project_name"),
            "created": manifest.get("created"),
            "engine_sha": engine.get("sha"),
            "engine_version": engine.get("version")}


def _manifest_problem(manifest: dict) -> str | None:
    schema = manifest.get("schema")
    if schema != MANIFEST_SCHEMA:
        return f"unsupported manifest schema: {schema!r}"
    init_status = manifest.get("status")
    if init_status != "ok":
        return f"manifest records init status {init_status!r}, not 'ok'"
    if not isinstance(manifest.get("engine"), dict):
        return "manifest engine record is malformed"
    return None


def _invalid_manifest_report(target: Path, manifest: dict, reason: str,
                             engine_root: Path | None) -> dict:
    blocked = _unknown(reason)
    integrity = dict(blocked)
    upstream = ({"verdict": NOT_CHECKED,
                 "reason": "no --engine-root given; staleness was not evaluated"}
                if engine_root is None else dict(blocked))
    return {"schema": SCHEMA, "target": target.as_posix(),
            "manifest": _manifest_summary(manifest),
            "integrity": integrity, "upstream": upstream,
            "verdict": UNKNOWN, "exit_code": EXIT_UNKNOWN}


def evaluate(target: Path, engine_root: Path | None = None) -> dict:
    """The full status report. Pure — takes paths, returns a dict, writes
    nothing, so tests and any future caller share one code path."""
    manifest = load_manifest(target)
    if manifest is None:
        return _no_manifest_report(target)
    problem = _manifest_problem(manifest)
    if problem:
        return _invalid_manifest_report(target, manifest, problem, engine_root)
    record = manifest["engine"].get("vendored")
    integrity = check_integrity(target, record)
    upstream = check_upstream(engine_root, record)
    verdict = _overall(integrity["verdict"], upstream["verdict"])
    return {"schema": SCHEMA, "target": target.as_posix(),
            "manifest": _manifest_summary(manifest),
            "integrity": integrity, "upstream": upstream,
            "verdict": verdict, "exit_code": EXIT_FOR[verdict]}


def _bucket_lines(bucket: str, entries: list) -> list[str]:
    shown = entries[:_MAX_LISTED]
    hidden = len(entries) - len(shown)
    lines = [f"      {bucket}: {rel}" for rel in shown]
    if hidden:
        lines.append(f"      {bucket}: and {hidden} more")
    return lines


def _axis_lines(name: str, axis: dict, buckets: tuple[str, ...]) -> list[str]:
    head = f"  {name:10} {axis['verdict'].upper()}"
    if axis.get("reason"):
        head += f" — {axis['reason']}"
    lines = [head]
    for bucket in buckets:
        lines.extend(_bucket_lines(bucket, axis.get(bucket) or []))
    return lines


def _header_lines(report: dict) -> list[str]:
    meta = report.get("manifest") or {}
    if not meta:
        return ["[sdlc status]"]
    lines = [f"[sdlc status] {meta.get('project_name')}  "
             f"engine={str(meta.get('engine_sha'))[:12]} "
             f"v{meta.get('engine_version')}  born={meta.get('created')}"]
    if meta.get("init_status") == "failed":
        lines.append("  WARNING: this repo's init recorded status=failed")
    return lines


def _report_lines(report: dict) -> list[str]:
    lines = _header_lines(report)
    lines += _axis_lines("integrity", report["integrity"],
                         ("modified", "missing", "extra"))
    lines += _axis_lines("upstream", report["upstream"],
                         ("changed", "added", "removed"))
    if report.get("reason"):
        lines.append(f"  {report['reason']}")
    lines.append(f"  verdict: {report['verdict'].upper()}")
    if report["upstream"].get("verdict") == DRIFT:
        lines.append("  " + _STALE_HINT.format(dest=hm.ENGINE_VENDOR_DEST))
    return lines


def run(target: Path, engine_root: Path | None, as_json: bool = False) -> int:
    report = evaluate(target, engine_root)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return report["exit_code"]
    for line in _report_lines(report):
        print(line)
    return report["exit_code"]


def build_arg_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--target", default=".",
                        help="Born-gated repo to inspect (default: cwd)")
    parser.add_argument("--engine-root", default=None,
                        help="Engine checkout to compare against. Omit to check "
                             "local integrity only (staleness is then reported "
                             "'not_checked', never 'ok')")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Emit the machine-readable report")
    return parser
