"""G1 input-sufficiency gate -- non-vacuous design tests.

Standalone: ``python -m pytest input-gate/tests/ -q``. Ships every Loop-3
anti-case so no guard can silently regress: a block gap blocks (exit 1, the gap
id named); the satisfied spec passes (exit 0); a failing warn is advisory (exit
0); an unknown kind fails closed (exit 2); a missing/invalid contract fails
closed; an inadmissible sufficiency judge is a LOUD skip that cannot gate; and
EACH evaluator both PASSES on a satisfying spec and FAILS (named gap) on a
violating one -- so no evaluator is a no-op. Delete a guard and this file goes
red.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "input-gate"))
sys.path.insert(0, str(ROOT / "schemas"))

from input_gate import (  # noqa: E402
    ContractInvalid,
    Gap,
    KindNotFound,
    MalformedCheck,
    PreflightResult,
    Severity,
    Spec,
    UnknownCheckType,
    evaluate_check,
    load_validated_dor,
    parse_spec,
    preflight,
    select_kind,
    sufficiency_skip_reason,
)
from input_gate.cli import main as cli_main  # noqa: E402
from input_gate.judge import (  # noqa: E402
    SKIP_INADMISSIBLE,
    SKIP_NO_ADAPTER,
    load_judge_bundle,
)
from sdlc_schemas import issues_to_findings, miniyaml  # noqa: E402
from sdlc_schemas.errors import SchemaIssue  # noqa: E402
from sdlc_schemas.linkcheck import build_bundle  # noqa: E402
from sdlc_schemas.registry import content_hash  # noqa: E402

_MODEL = "judge-model-2026-05"


# ── contract + spec fixtures (miniyaml strict subset, mirrors the shape doc) ──

_DOR_SECTION = (
    "schema: 'sdlc/def-of-ready@1'\n"
    "owner: '@org/delivery-leads'\n"
    "kinds:\n"
    "  application:\n"
    "    requires:\n"
    "      - id: acceptance-criteria\n"
    "        description: 'Spec has an Acceptance Criteria section defined.'\n"
    "        severity: block\n"
    "        check:\n"
    "          type: section_present\n"
    "          heading: 'Acceptance Criteria'\n"
)

_DOR_FIELD = (
    "schema: 'sdlc/def-of-ready@1'\n"
    "owner: '@org/delivery-leads'\n"
    "kinds:\n"
    "  application:\n"
    "    requires:\n"
    "      - id: owner-declared\n"
    "        description: 'Spec declares an owning team in front-matter.'\n"
    "        severity: block\n"
    "        check:\n"
    "          type: field_present\n"
    "          path: 'owner.team'\n"
)

_DOR_WARN = (
    "schema: 'sdlc/def-of-ready@1'\n"
    "owner: '@org/delivery-leads'\n"
    "kinds:\n"
    "  application:\n"
    "    requires:\n"
    "      - id: rollback-noted\n"
    "        description: 'Spec mentions a rollback or kill-switch plan.'\n"
    "        severity: warn\n"
    "        check:\n"
    "          type: pattern_present\n"
    "          pattern: '(?i)rollback|kill.?switch'\n"
)

_DOR_JUDGE = (
    "schema: 'sdlc/def-of-ready@1'\n"
    "owner: '@org/delivery-leads'\n"
    "kinds:\n"
    "  application:\n"
    "    requires:\n"
    "      - id: acceptance-criteria\n"
    "        description: 'Spec has an Acceptance Criteria section defined.'\n"
    "        severity: block\n"
    "        check:\n"
    "          type: section_present\n"
    "          heading: 'Acceptance Criteria'\n"
    "    sufficiency_judge:\n"
    "      rubric: 'spec-sufficiency@1'\n"
)

# A kind whose only requirement is an empty checklist -> E1.7 E-MIN-ITEMS (the
# def-of-ready shape's own vacuous-green anti-case).
_DOR_INVALID = (
    "schema: 'sdlc/def-of-ready@1'\n"
    "owner: '@org/delivery-leads'\n"
    "kinds:\n"
    "  application:\n"
    "    requires: []\n"
)

_RUBRIC_UNCALIBRATED = (
    "schema: 'sdlc/rubric@1'\n"
    "id: spec-sufficiency\n"
    "version: 1\n"
)

_SPEC_WITH_SECTION = "# Acceptance Criteria\n\nThe app must satisfy X and Y.\n"
_SPEC_NO_SECTION = "# Overview\n\nProse with no required section here.\n"
_SPEC_WITH_ROLLBACK = "# Plan\n\nWe roll back via the documented kill switch.\n"
_SPEC_NO_ROLLBACK = "# Plan\n\nNo mention of reverting the change.\n"
_SPEC_WITH_TEAM = "---\nowner:\n  team: platform\n---\n# Spec\n\nBody.\n"
_SPEC_NO_TEAM = "---\nowner:\n  name: unnamed\n---\n# Spec\n\nBody.\n"


def _write_overlay(tmp, dor_yaml, rubric_yaml=None):
    """Materialise a ``.sdlc-core`` overlay: the def-of-ready and an optional
    rubric under ``rubrics/`` (for the judge choke). Returns the core dir."""
    core = Path(tmp) / ".sdlc-core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "def-of-ready.yaml").write_text(dor_yaml, encoding="utf-8")
    if rubric_yaml is not None:
        rubrics = core / "rubrics"
        rubrics.mkdir(parents=True, exist_ok=True)
        (rubrics / "spec-sufficiency.yaml").write_text(rubric_yaml, encoding="utf-8")
    return core


def _write_spec(tmp, text):
    path = Path(tmp) / "spec.md"
    path.write_text(text, encoding="utf-8")
    return path


def _preflight_cli(tmp, dor_yaml, spec_text, kind="application", rubric=None):
    core = _write_overlay(tmp, dor_yaml, rubric)
    spec = _write_spec(tmp, spec_text)
    return cli_main(["preflight", str(spec), "--kind", kind,
                     "--core-dir", str(core), "--judge-model", _MODEL])


# ── anti-case 1 + 2: a block gap blocks (id named); the satisfied spec passes ─

def test_block_gap_blocks_and_names_the_gap_id(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_SECTION, _SPEC_NO_SECTION)
    assert code == 1
    assert "acceptance-criteria" in capsys.readouterr().err


def test_satisfied_spec_passes(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_SECTION, _SPEC_WITH_SECTION)
    assert code == 0
    assert "preflight ok" in capsys.readouterr().err


# ── anti-case 3: a failing warn is advisory (exit 0, advisory in findings) ────

def test_failing_warn_is_advisory_not_a_block(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_WARN, _SPEC_NO_ROLLBACK)
    err = capsys.readouterr().err
    assert code == 0
    assert "rollback-noted" in err and "warn" in err


def test_passing_warn_leaves_no_advisory(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_WARN, _SPEC_WITH_ROLLBACK)
    assert code == 0
    assert "advisories=0" in capsys.readouterr().err


# ── anti-case 4: an unknown --kind fails closed (exit 2), never a vacuous pass ─

def test_unknown_kind_fails_closed(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_SECTION, _SPEC_WITH_SECTION, kind="nonesuch")
    assert code == 2
    assert "nonesuch" in capsys.readouterr().err


def test_select_kind_raises_on_unknown():
    contract = {"kinds": {"application": {"requires": []}}}
    assert select_kind(contract, "application") == {"requires": []}
    try:
        select_kind(contract, "ghost")
    except KindNotFound as exc:
        assert "application" in exc.available
        return
    raise AssertionError("select_kind must fail closed on an unknown kind")


# ── anti-case 5: a missing/empty contract fails closed (exit 2) ───────────────

def test_missing_contract_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        spec = _write_spec(tmp, _SPEC_WITH_SECTION)
        core = Path(tmp) / ".sdlc-core"
        code = cli_main(["preflight", str(spec), "--kind", "application",
                         "--core-dir", str(core)])
    assert code == 2


def test_load_validated_dor_missing_raises_file_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_validated_dor(Path(tmp) / ".sdlc-core")
        except FileNotFoundError:
            return
    raise AssertionError("a missing def-of-ready must fail closed")


# ── anti-case 6: an E1.7-invalid contract is refused upstream ─────────────────

def test_invalid_contract_is_refused_upstream():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_overlay(tmp, _DOR_INVALID)
        try:
            load_validated_dor(core)
        except ContractInvalid as exc:
            rules = {finding["rule"] for finding in exc.findings}
            # pinned: the empty checklist -> E1.7 E-MIN-ITEMS, not some unrelated
            # failure that would make this anti-case vacuous.
            assert "SCHEMA-E-MIN-ITEMS" in rules, rules
            return
    raise AssertionError("G1 must refuse an E1.7-invalid def-of-ready")


def test_cli_fails_closed_on_invalid_contract():
    with tempfile.TemporaryDirectory() as tmp:
        code = _preflight_cli(tmp, _DOR_INVALID, _SPEC_WITH_SECTION)
    assert code == 2


# ── anti-case 7: an inadmissible sufficiency judge cannot gate ────────────────

def _rubric(kappa, *, model=_MODEL, calibrated=True, probe="probe-tag"):
    rubric = {
        "schema": "sdlc/rubric@1", "id": "spec-sufficiency", "version": 1,
        "prompt": "Score each criterion against the definitions below.",
        "scale": {"min": 0, "max": 4}, "threshold": 3,
        "criteria": [{"id": "goal-clarity", "description": "goal is testable"}],
        "meta_eval": {"probe_tag": probe},
    }
    if calibrated:
        rubric["calibration"] = {
            "kappa": kappa, "sample_size": 60, "measured_at": "2026-06-30",
            "binding": {"model_id": model, "content_hash": content_hash(rubric)},
        }
    return rubric


def _anti_probe(tag):
    return {"schema": "sdlc/golden-case@1", "id": "anti-probe", "kind": "anti_case",
            "determinism": "deterministic", "status": "active",
            "lineage": {"route": "red_team"}, "tags": [tag],
            "target_kind": "assertion", "expected_verdict": "fail", "payload": {}}


def _bundle_with(rubric, probe="probe-tag"):
    return build_bundle([("sdlc/rubric@1", rubric),
                         ("sdlc/golden-case@1", _anti_probe(probe))])


def _judge_kind():
    return {"requires": [], "sufficiency_judge": {"rubric": "spec-sufficiency@1"}}


def test_uncalibrated_rubric_is_a_loud_skip():
    bundle = _bundle_with(_rubric(0.0, calibrated=False))
    reason = sufficiency_skip_reason(_judge_kind(), bundle, _MODEL)
    assert reason.startswith(SKIP_INADMISSIBLE) and "uncalibrated" in reason


def test_below_floor_kappa_is_a_loud_skip():
    reason = sufficiency_skip_reason(_judge_kind(), _bundle_with(_rubric(0.5)), _MODEL)
    assert reason.startswith(SKIP_INADMISSIBLE) and "below floor" in reason


def test_admissible_rubric_still_skips_and_never_passes():
    # The strongest form of "the judge cannot gate green": even a fully
    # calibrated, model-matched, probe-resolved rubric only SKIPS (no adapter).
    reason = sufficiency_skip_reason(_judge_kind(), _bundle_with(_rubric(0.9)), _MODEL)
    assert reason.startswith(SKIP_NO_ADAPTER)


def test_no_judge_configured_is_none():
    assert sufficiency_skip_reason({"requires": []}, {}, _MODEL) is None


def test_inadmissible_judge_does_not_rescue_a_block_gap():
    # deterministic block MISSES + judge inadmissible -> still not ok (the judge
    # never turns red to green).
    kind = {"requires": [{"id": "acceptance-criteria",
                          "description": "Spec has an Acceptance Criteria section.",
                          "severity": "block",
                          "check": {"type": "section_present",
                                    "heading": "Acceptance Criteria"}}],
            "sufficiency_judge": {"rubric": "spec-sufficiency@1"}}
    spec = Spec(front_matter={}, body=_SPEC_NO_SECTION, file="spec.md")
    result = preflight(kind, "application", spec,
                       bundle=_bundle_with(_rubric(0.5)), judge_model_id=_MODEL)
    assert result.ok is False
    assert result.skips and result.skips[0].startswith(SKIP_INADMISSIBLE)


def test_inadmissible_judge_does_not_break_a_passing_run():
    # deterministic block PASSES + judge inadmissible -> ok stays True, the skip
    # is present but purely advisory.
    kind = {"requires": [{"id": "acceptance-criteria",
                          "description": "Spec has an Acceptance Criteria section.",
                          "severity": "block",
                          "check": {"type": "section_present",
                                    "heading": "Acceptance Criteria"}}],
            "sufficiency_judge": {"rubric": "spec-sufficiency@1"}}
    spec = Spec(front_matter={}, body=_SPEC_WITH_SECTION, file="spec.md")
    result = preflight(kind, "application", spec,
                       bundle=_bundle_with(_rubric(0.5)), judge_model_id=_MODEL)
    assert result.ok is True and result.evaluated == 1
    assert result.skips and result.skips[0].startswith(SKIP_INADMISSIBLE)


def test_cli_inadmissible_judge_skips_loudly_both_ways(capsys):
    # Satisfied deterministic block + inadmissible judge -> exit 0 with the skip
    # visible; the verdict came from the check, not the judge.
    with tempfile.TemporaryDirectory() as tmp:
        ok_code = _preflight_cli(tmp, _DOR_JUDGE, _SPEC_WITH_SECTION,
                                 rubric=_RUBRIC_UNCALIBRATED)
    ok_err = capsys.readouterr().err
    assert ok_code == 0
    assert SKIP_INADMISSIBLE in ok_err and "JUDGE SKIP" in ok_err
    with tempfile.TemporaryDirectory() as tmp:
        block_code = _preflight_cli(tmp, _DOR_JUDGE, _SPEC_NO_SECTION,
                                    rubric=_RUBRIC_UNCALIBRATED)
    block_err = capsys.readouterr().err
    assert block_code == 1
    assert SKIP_INADMISSIBLE in block_err


def test_load_judge_bundle_keys_overlay_rubrics():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_overlay(tmp, _DOR_JUDGE, _RUBRIC_UNCALIBRATED)
        bundle = load_judge_bundle(core)
    assert ("spec-sufficiency", 1) in bundle["rubrics"]


# ── anti-case 8: each evaluator both ways (no evaluator is a no-op) ────────────

def test_section_present_passes_and_fails():
    check = {"type": "section_present", "heading": "Acceptance Criteria"}
    ok, _ = evaluate_check(check, Spec({}, "## Acceptance Criteria\n", "s"))
    assert ok is True
    bad, detail = evaluate_check(check, Spec({}, "## Something Else\n", "s"))
    assert bad is False and "Acceptance Criteria" in detail
    empty, _ = evaluate_check(check, Spec({}, "", "s"))
    assert empty is False


def test_field_present_passes_and_fails():
    check = {"type": "field_present", "path": "owner.team"}
    ok, _ = evaluate_check(check, Spec({"owner": {"team": "platform"}}, "", "s"))
    assert ok is True
    missing, detail = evaluate_check(check, Spec({"owner": {"name": "x"}}, "", "s"))
    assert missing is False and "owner.team" in detail
    empty_value, _ = evaluate_check(check, Spec({"owner": {"team": ""}}, "", "s"))
    assert empty_value is False


def test_pattern_present_passes_and_fails():
    check = {"type": "pattern_present", "pattern": "(?i)rollback|kill.?switch"}
    ok, _ = evaluate_check(check, Spec({}, "We will rollback safely.", "s"))
    assert ok is True
    bad, detail = evaluate_check(check, Spec({}, "no reverting here", "s"))
    assert bad is False and "did not match" in detail


def test_field_present_rejects_whitespace_value():
    # BLOCKER regression: a whitespace-only value satisfies nothing.
    check = {"type": "field_present", "path": "owner.team"}
    for blank in ("   ", "\t", "\n  "):
        got, _ = evaluate_check(check, Spec({"owner": {"team": blank}}, "", "s"))
        assert got is False, repr(blank)


def test_section_present_ignores_code_fence_heading():
    # BLOCKER regression: a '#' line inside a ``` fence is code, not a heading, so
    # it must not satisfy a block section_present requirement.
    check = {"type": "section_present", "heading": "Acceptance Criteria"}
    fenced = "```markdown\n# Acceptance Criteria\n```\n"
    assert evaluate_check(check, Spec({}, fenced, "s"))[0] is False
    real = fenced + "# Acceptance Criteria\n"
    assert evaluate_check(check, Spec({}, real, "s"))[0] is True


def test_pattern_present_ignores_comment_and_fence():
    # a requirement is not satisfied by a mention in a comment or a code sample.
    check = {"type": "pattern_present", "pattern": "(?i)rollback"}
    commented = "<!-- TODO: add a rollback plan -->\nno plan here\n"
    assert evaluate_check(check, Spec({}, commented, "s"))[0] is False
    fenced = "```\nrollback\n```\nno plan here\n"
    assert evaluate_check(check, Spec({}, fenced, "s"))[0] is False
    assert evaluate_check(check, Spec({}, "We will rollback safely.\n", "s"))[0] is True


def test_unknown_check_type_fails_closed():
    try:
        evaluate_check({"type": "llm_vibes"}, Spec({}, "x", "s"))
    except UnknownCheckType:
        return
    raise AssertionError("an unknown check type must fail closed, never skip")


def test_malformed_check_missing_argument_fails_closed():
    for check in ({"type": "section_present"}, {"type": "field_present"},
                  {"type": "pattern_present"}):
        try:
            evaluate_check(check, Spec({}, "x", "s"))
        except MalformedCheck:
            continue
        raise AssertionError(f"a check missing its argument must fail closed: {check}")


def test_invalid_regex_is_malformed_not_a_crash():
    try:
        evaluate_check({"type": "pattern_present", "pattern": "(unclosed"},
                       Spec({}, "text", "s"))
    except MalformedCheck:
        return
    raise AssertionError("an invalid regex must fail closed as MalformedCheck")


# ── spec parsing: front-matter split + fail-closed on bad YAML ────────────────

def test_parse_spec_splits_front_matter_from_body():
    with tempfile.TemporaryDirectory() as tmp:
        spec = parse_spec(_write_spec(tmp, _SPEC_WITH_TEAM))
    assert spec.front_matter == {"owner": {"team": "platform"}}
    assert "# Spec" in spec.body and "---" not in spec.body


def test_parse_spec_without_front_matter_is_all_body():
    with tempfile.TemporaryDirectory() as tmp:
        spec = parse_spec(_write_spec(tmp, _SPEC_WITH_SECTION))
    assert spec.front_matter == {}
    assert spec.body == _SPEC_WITH_SECTION


def test_parse_spec_rejects_out_of_subset_front_matter():
    with tempfile.TemporaryDirectory() as tmp:
        bad = _write_spec(tmp, "---\nowner: {team: x}\n---\n# Body\n")
        try:
            parse_spec(bad)
        except miniyaml.MiniYAMLError:
            return
    raise AssertionError("front-matter outside the YAML subset must fail closed")


def test_cli_field_present_through_front_matter(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        ok_code = _preflight_cli(tmp, _DOR_FIELD, _SPEC_WITH_TEAM)
    assert ok_code == 0
    with tempfile.TemporaryDirectory() as tmp:
        gap_code = _preflight_cli(tmp, _DOR_FIELD, _SPEC_NO_TEAM)
    assert gap_code == 1
    assert "owner-declared" in capsys.readouterr().err


# ── PreflightResult.ok fails closed on every vacuous shape ────────────────────

def _block_gap():
    return Gap(rule="G1-BLOCK-GAP", requirement_id="x", severity=Severity.ERROR,
               message="x: missing", file="s")


def _advisory():
    return Gap(rule="G1-WARN-ADVISORY", requirement_id="y", severity=Severity.WARNING,
               message="y: missing", file="s")


def test_preflight_result_ok_requires_kind_evaluated_and_no_block_gap():
    assert PreflightResult(kind="", evaluated=1).ok is False        # no kind
    assert PreflightResult(kind="application", evaluated=0).ok is False  # nothing ran
    assert PreflightResult(kind="application", evaluated=1,
                           gaps=(_block_gap(),)).ok is False         # block gap
    assert PreflightResult(kind="application", evaluated=1,
                           advisories=(_advisory(),)).ok is True     # warn is fine


def test_findings_reuse_the_quality_gate_shape():
    result = PreflightResult(kind="application", evaluated=1,
                             gaps=(_block_gap(),), advisories=(_advisory(),))
    finding = result.findings()[0]
    schema_finding = issues_to_findings(
        [SchemaIssue(code="E-SYNTAX", path="", message="m", file="f")]
    )[0]
    assert set(finding) == set(schema_finding)   # same reporting contract, not forked
    assert finding["severity"] == "error"
    assert len(result.findings()) == 2


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
