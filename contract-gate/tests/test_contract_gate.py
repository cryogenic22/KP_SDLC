"""G2 metric-contract completeness gate -- non-vacuous design tests.

Standalone-runnable: ``python -m pytest contract-gate/tests/ -q``. Ships every
Loop-3 anti-case so no guard can silently regress: a dangling reference blocks
(exit 1, the id AND the library owner named); an all-resolve artifact passes
(exit 0); a malformed artifact fails closed (exit 2); a missing/invalid library
fails closed (exit 2, ContractInvalid); an unreferenced library metric is a warn
advisory that never blocks (exit 0); and -- the vacuous-green pin -- the id
extractor is proven REAL: a report with 3 distinct refs has all 3 checked, so a
no-op extractor that returned ``[]`` would turn multiple anti-cases RED. Delete a
guard and this file goes red.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contract-gate"))
sys.path.insert(0, str(ROOT / "runtime-verify"))
sys.path.insert(0, str(ROOT / "schemas"))

from contract_gate import (  # noqa: E402
    ContractCheckResult,
    ContractInvalid,
    Gap,
    MalformedArtifact,
    RULE_UNREPORTED,
    RULE_UNRESOLVED,
    Severity,
    check_contract,
    extract_metric_ids,
    load_validated_library,
    parse_artifact,
)
from contract_gate.cli import main as cli_main  # noqa: E402
from sdlc_schemas import issues_to_findings  # noqa: E402
from sdlc_schemas.errors import SchemaIssue  # noqa: E402


# ── library fixtures (miniyaml strict subset, mirrors the shape doc) ──────────

_LIBRARY_TWO = (
    "schema: sdlc/metric-library@1\n"
    "owner: '@team/analytics'\n"
    "metrics:\n"
    "  revenue_total:\n"
    "    grain:\n"
    "      - date\n"
    "    source:\n"
    "      system: stub\n"
    "      ref: 'rev.ref'\n"
    "    owner: '@team/finance'\n"
    "    tolerance:\n"
    "      type: absolute\n"
    "      value: 0\n"
    "  active_users:\n"
    "    grain: []\n"
    "    source:\n"
    "      system: stub\n"
    "      ref: 'users.ref'\n"
    "    owner: '@team/product'\n"
    "    tolerance:\n"
    "      type: absolute\n"
    "      value: 0\n"
)

# Same instance with the required `tolerance` removed -> E1.7 E-REQUIRED.
_LIBRARY_INVALID = (
    "schema: sdlc/metric-library@1\n"
    "owner: '@team/analytics'\n"
    "metrics:\n"
    "  revenue_total:\n"
    "    grain:\n"
    "      - date\n"
    "    source:\n"
    "      system: stub\n"
    "      ref: 'rev.ref'\n"
    "    owner: '@team/finance'\n"
)


def _metric(owner="@team/data"):
    return {
        "grain": ["date"],
        "source": {"system": "stub", "ref": "r.ref"},
        "owner": owner,
        "tolerance": {"type": "absolute", "value": 0},
    }


def _library(metrics, owner="@team/analytics"):
    return {"schema": "sdlc/metric-library@1", "owner": owner, "metrics": metrics}


def _write_core(tmp, library_yaml):
    core = Path(tmp) / ".sdlc-core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "metric-library.yaml").write_text(library_yaml, encoding="utf-8")
    return core


def _write_artifact(tmp, text, name="report.yaml"):
    path = Path(tmp) / name
    path.write_text(text, encoding="utf-8")
    return path


def _contract_cli(tmp, library_yaml, artifact_text, name="report.yaml"):
    core = _write_core(tmp, library_yaml)
    art = _write_artifact(tmp, artifact_text, name)
    return cli_main(["contract", str(art), "--core-dir", str(core)])


# ── anti-case 1 + 3: dangling ref blocks (id named, library owner rendered) ───

def test_dangling_reference_blocks_and_names_id_and_owner():
    result = check_contract(_library({"revenue_total": _metric()}),
                            ["ghost_metric"], contract_path="lib.yaml")
    assert result.ok is False
    blocks = [gap for gap in result.gaps if gap.rule == RULE_UNRESOLVED]
    assert len(blocks) == 1
    assert blocks[0].metric_id == "ghost_metric"
    # anti-case 3: a dangling id has no library entry, so the LIBRARY-level owner
    # is the rendered accountability fallback (not an empty string).
    assert blocks[0].owner == "@team/analytics"
    assert "ghost_metric" in blocks[0].message and "@team/analytics" in blocks[0].message


def test_cli_dangling_blocks_exit_1_with_id_and_owner(capsys):
    art = "metrics:\n  - id: ghost_metric\n    value: 5\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art)
    err = capsys.readouterr().err
    assert code == 1
    assert "ghost_metric" in err
    assert "@team/analytics" in err  # library owner rendered on the block


# ── anti-case 2: an all-resolve artifact passes (exit 0) ──────────────────────

def test_all_resolved_references_pass():
    entry = _metric()
    result = check_contract(
        _library({"revenue_total": entry, "active_users": entry}),
        ["revenue_total", "active_users"])
    assert result.ok is True
    assert result.checked == 2
    assert not result.gaps


def test_cli_all_resolve_exit_0(capsys):
    art = "metrics:\n  - id: revenue_total\n  - id: active_users\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art)
    assert code == 0
    assert "contract ok" in capsys.readouterr().err


def test_cli_bare_id_form_all_resolve_exit_0():
    art = "metrics:\n  - revenue_total\n  - active_users\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art)
    assert code == 0


def test_cli_json_artifact_dangling_exit_1(capsys):
    art = json.dumps({"metrics": [{"id": "ghost_metric", "value": 1}]})
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art, name="report.json")
    assert code == 1
    assert "ghost_metric" in capsys.readouterr().err


# ── anti-case 6: the extractor is REAL (returns every id the artifact holds) ───

def test_extractor_returns_every_referenced_id_in_order():
    # A no-op extractor returning [] fails this directly; the count is the pin.
    data = {"metrics": [{"id": "a_one", "value": 1},
                        {"id": "b_two", "value": 2},
                        {"id": "c_three", "value": 3}]}
    assert extract_metric_ids(data) == ["a_one", "b_two", "c_three"]


def test_extractor_bare_id_form():
    assert extract_metric_ids({"metrics": ["a_one", "b_two"]}) == ["a_one", "b_two"]


def test_extractor_dedupes_repeated_reference_but_keeps_distinct():
    assert extract_metric_ids({"metrics": ["a_one", "a_one", "b_two"]}) == ["a_one", "b_two"]


def test_three_distinct_dangling_refs_are_all_checked_and_block():
    # If extraction regressed to [], checked would be 0 and result.ok True -> RED.
    lib = _library({"revenue_total": _metric()})
    ids = extract_metric_ids({"metrics": [{"id": "x_one"}, {"id": "y_two"}, {"id": "z_three"}]})
    result = check_contract(lib, ids)
    assert result.checked == 3
    assert len(result.gaps) == 3
    assert result.ok is False


def test_cli_three_distinct_dangling_refs_all_named_exit_1(capsys):
    art = "metrics:\n  - id: x_one\n  - id: y_two\n  - id: z_three\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art)
    err = capsys.readouterr().err
    assert code == 1
    assert "gaps=3" in err
    for metric_id in ("x_one", "y_two", "z_three"):
        assert metric_id in err


# ── anti-case 4: a malformed artifact fails closed (exit 2), never a pass ──────

def test_malformed_artifact_shapes_fail_closed():
    malformed = (
        {"metrics": [{"value": 5}]},          # object entry with no id
        {"metrics": [{"id": 123}]},           # non-string id
        {"metrics": [{"id": True}]},          # bool id (not a string)
        {"metrics": [{"id": ""}]},            # empty id
        {"metrics": [{"id": "  "}]},          # whitespace-only id
        {"metrics": [123]},                   # entry neither bare id nor object
        {"metrics": [True]},                  # bool entry
        {"metrics": "revenue_total"},         # metrics not a list
        {"no_metrics": []},                   # no metrics key
        None,                                 # empty document
        ["metrics"],                          # not a mapping
    )
    for data in malformed:
        try:
            extract_metric_ids(data)
        except MalformedArtifact:
            continue
        raise AssertionError(f"a malformed artifact must fail closed: {data!r}")


def test_empty_metrics_list_is_zero_references_not_malformed():
    # A report may legitimately reference no metric -- nothing to dangle.
    assert extract_metric_ids({"metrics": []}) == []


def test_cli_malformed_object_without_id_fails_closed_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, "metrics:\n  - value: 5\n")
    assert code == 2


def test_cli_metrics_not_a_list_fails_closed_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, "metrics: revenue_total\n")
    assert code == 2


def test_cli_unparseable_artifact_fails_closed_exit_2():
    # a tab in indentation -> miniyaml E-SYNTAX, mapped to a loud exit 2.
    bad = "metrics:\n\t- id: revenue_total\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, bad)
    assert code == 2


def test_cli_missing_artifact_fails_closed_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _LIBRARY_TWO)
        code = cli_main(["contract", str(Path(tmp) / "nope.yaml"), "--core-dir", str(core)])
    assert code == 2


# ── anti-case 5: a missing/invalid metric-library fails closed (exit 2) ────────

def test_cli_missing_library_fails_closed_exit_2():
    art = "metrics:\n  - id: revenue_total\n"
    with tempfile.TemporaryDirectory() as tmp:
        art_path = _write_artifact(tmp, art)
        core = Path(tmp) / ".sdlc-core"  # deliberately not created
        code = cli_main(["contract", str(art_path), "--core-dir", str(core)])
    assert code == 2


def test_cli_invalid_library_fails_closed_exit_2(capsys):
    art = "metrics:\n  - id: revenue_total\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_INVALID, art)
    err = capsys.readouterr().err
    assert code == 2
    assert "E-REQUIRED" in err  # pinned: the missing tolerance, not some unrelated fail


def test_invalid_library_raises_contract_invalid():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _LIBRARY_INVALID)
        try:
            load_validated_library(core)
        except ContractInvalid as exc:
            rules = {finding["rule"] for finding in exc.findings}
            assert "SCHEMA-E-REQUIRED" in rules, rules
            return
    raise AssertionError("G2 must refuse an E1.7-invalid metric-library")


def test_load_validated_library_missing_raises_file_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_validated_library(Path(tmp) / ".sdlc-core")
        except FileNotFoundError:
            return
    raise AssertionError("a missing metric-library must fail closed")


# ── anti-case 7: an unreferenced library metric is a warn advisory (exit 0) ────

def test_unreferenced_library_metric_is_warn_not_block():
    lib = _library({"revenue_total": _metric(owner="@team/finance"),
                    "active_users": _metric(owner="@team/product")})
    result = check_contract(lib, ["revenue_total"])
    assert result.ok is True  # the advisory does NOT block
    advisories = [gap for gap in result.advisories if gap.rule == RULE_UNREPORTED]
    assert len(advisories) == 1
    assert advisories[0].metric_id == "active_users"
    assert advisories[0].severity is Severity.WARNING
    assert advisories[0].owner == "@team/product"  # the metric's own owner


def test_cli_unreported_metric_is_advisory_exit_0(capsys):
    art = "metrics:\n  - id: revenue_total\n"
    with tempfile.TemporaryDirectory() as tmp:
        code = _contract_cli(tmp, _LIBRARY_TWO, art)
    err = capsys.readouterr().err
    assert code == 0
    assert "active_users" in err and "warn" in err


def test_zero_references_is_a_clean_pass_with_advisories():
    lib = _library({"revenue_total": _metric()})
    result = check_contract(lib, [])
    assert result.ok is True
    assert result.checked == 0
    assert not result.gaps
    assert any(gap.rule == RULE_UNREPORTED for gap in result.advisories)


# ── model: ok fails CLOSED on a block gap; the shared finding shape is reused ──

def test_result_ok_requires_no_block_gap():
    block = Gap(rule=RULE_UNRESOLVED, metric_id="x", severity=Severity.ERROR, message="m")
    warn = Gap(rule=RULE_UNREPORTED, metric_id="y", severity=Severity.WARNING, message="m")
    assert ContractCheckResult(checked=1, gaps=(block,)).ok is False   # dangling blocks
    assert ContractCheckResult(checked=1, advisories=(warn,)).ok is True  # warn is fine
    assert ContractCheckResult(checked=0).ok is True                   # nothing to dangle


def test_findings_reuse_the_quality_gate_shape():
    block = Gap(rule=RULE_UNRESOLVED, metric_id="x", severity=Severity.ERROR,
                message="m", file="lib.yaml")
    warn = Gap(rule=RULE_UNREPORTED, metric_id="y", severity=Severity.WARNING,
               message="m", file="lib.yaml")
    result = ContractCheckResult(checked=1, gaps=(block,), advisories=(warn,))
    findings = result.findings()
    finding = findings[0]
    schema_finding = issues_to_findings(
        [SchemaIssue(code="E-SYNTAX", path="", message="m", file="f")]
    )[0]
    assert set(finding) == set(schema_finding)  # same reporting contract, not forked
    assert finding["severity"] == "error"
    assert finding["file"] == "lib.yaml"
    assert len(findings) == 2


# ── parse_artifact reads both YAML and JSON and fails closed on absence ────────

def test_parse_artifact_reads_yaml_and_json():
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = _write_artifact(tmp, "metrics:\n  - id: revenue_total\n")
        json_path = _write_artifact(tmp, json.dumps({"metrics": ["revenue_total"]}),
                                    name="report.json")
        assert extract_metric_ids(parse_artifact(yaml_path)) == ["revenue_total"]
        assert extract_metric_ids(parse_artifact(json_path)) == ["revenue_total"]


def test_parse_artifact_missing_file_raises_oserror():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            parse_artifact(Path(tmp) / "absent.yaml")
        except OSError:
            return
    raise AssertionError("a missing report artifact must raise, never return empty")


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
