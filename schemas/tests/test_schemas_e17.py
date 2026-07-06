"""E1.7 core/overlay schema harness — design tests (a)-(h).

Standalone-runnable: ``python schemas/tests/test_schemas_e17.py``.
Parametrized over the six shipped shape docs via the registry. Each schema
embeds its own x-valid-cases / x-anti-cases, so the corpus travels with the
shapes (no vacuous green: >=1 valid + >=3 anti pinned to the CLOSED code enum).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdlc_schemas import (  # noqa: E402
    KAPPA_FLOOR,
    check_overlay,
    iter_anti_cases,
    iter_valid_cases,
    issues_to_findings,
    load_document,
    load_schema,
    validate,
)
from sdlc_schemas import linkcheck, miniyaml, shapecheck  # noqa: E402
from sdlc_schemas.errors import CODES, SchemaDefinitionError, SchemaIssue  # noqa: E402
from sdlc_schemas.registry import KNOWN, Inadmissible, resolve_rubric  # noqa: E402

SHAPES = Path(__file__).resolve().parents[1] / "sdlc_schemas" / "shapes"
STARTERS = Path(__file__).resolve().parents[1] / "sdlc_schemas" / "starters"
SHAPE_KEYWORDS = ("$id", "$defs", "$schema", "x-consumer", "x-consumers",
                  "x-valid-cases", "x-anti-cases", "properties",
                  "additionalProperties", "propertyNames")


def _schemas():
    return {tag: load_schema(tag) for tag in KNOWN}


def _err_codes(issues):
    return {i.code for i in issues if i.severity == "error"}


# ── errors.py: the CLOSED 23-code enum ────────────────────────────────

def test_error_enum_has_exactly_23_codes():
    count = len(CODES)
    assert count == 23, f"code enum drifted: {count} codes"
    assert len(set(CODES)) == count, "duplicate code in the enum"


def test_undefined_code_is_refused():
    ok = SchemaIssue(code="E-SYNTAX", path="", message="m")
    assert ok.code == "E-SYNTAX"
    try:
        SchemaIssue(code="E-MADE-UP", path="", message="m")
    except ValueError:
        return
    raise AssertionError("constructing an out-of-enum code must raise")


# ── miniyaml: strict subset, fail-closed ──────────────────────────────

def test_miniyaml_flow_collection_is_syntax_error():
    try:
        miniyaml.load("a: [1, 2, 3]\n")
    except miniyaml.MiniYAMLError as exc:
        assert exc.code == "E-SYNTAX"
        return
    raise AssertionError("a flow collection must raise E-SYNTAX")


def test_miniyaml_block_doc_round_trips_with_lines():
    data, lines = miniyaml.load("owner: '@org/x'\nkinds:\n  app:\n    n: 1\n")
    assert data == {"owner": "@org/x", "kinds": {"app": {"n": 1}}}
    assert lines[("owner",)] == 1
    assert lines[("kinds",)] == 2


def test_miniyaml_rejects_tabs_and_anchors():
    for bad in ("a:\n\tb: 1\n", "a: &anchor 1\n", "a: *ref\n", "a: !tag v\n"):
        try:
            miniyaml.load(bad)
        except miniyaml.MiniYAMLError as exc:
            assert exc.code == "E-SYNTAX", bad
            continue
        raise AssertionError(f"expected E-SYNTAX for {bad!r}")


# ── (a) every x-valid-case validates clean ────────────────────────────

def test_a_valid_cases_validate_clean():
    for tag, schema in _schemas().items():
        cases = iter_valid_cases(schema)
        assert cases, f"{tag}: no x-valid-cases"
        for case in cases:
            issues = validate(case["instance"], schema, file=case["name"],
                              bundle=case.get("bundle"))
            assert _err_codes(issues) == set(), \
                f"{tag}/{case['name']} should be clean, got {issues}"


# ── (b) every x-anti-case yields exactly its must_fail_with code ──────

def test_b_anti_cases_yield_exact_code():
    for tag, schema in _schemas().items():
        for case in iter_anti_cases(schema):
            issues = validate(case["instance"], schema, file=case["name"],
                              bundle=case.get("bundle"))
            got = _err_codes(issues)
            assert got == {case["must_fail_with"]}, \
                f"{tag}/{case['name']}: expected {case['must_fail_with']}, got {got}"


# ── (c) >=1 valid + >=3 anti per schema ───────────────────────────────

def test_c_no_vacuous_green_case_counts():
    for tag, schema in _schemas().items():
        assert len(iter_valid_cases(schema)) >= 1, f"{tag}: need >=1 valid case"
        assert len(iter_anti_cases(schema)) >= 3, f"{tag}: need >=3 anti-cases"


# ── (d) bidirectional engine/overlay split ────────────────────────────

def test_d_shape_docs_are_not_instances():
    for path in sorted(SHAPES.iterdir()):
        data, _ = load_document(path)
        assert "schema" not in data, f"{path.name} carries an instance tag"
        assert "$id" in data, f"{path.name} missing $id (not a shape doc)"


def test_d_starters_carry_no_shape_keywords():
    for path in _starter_files():
        data, _ = load_document(path)
        assert "schema" in data, f"{path.name} is not an instance"
        _assert_no_shape_keywords(data, path.name)


def _assert_no_shape_keywords(node, name):
    if isinstance(node, dict):
        for key, val in node.items():
            assert key not in SHAPE_KEYWORDS, f"{name}: shape keyword {key!r} leaked"
            _assert_no_shape_keywords(val, name)
    elif isinstance(node, list):
        for item in node:
            _assert_no_shape_keywords(item, name)


def _starter_files():
    return sorted(p for p in STARTERS.rglob("*.yaml"))


# ── (e) starters fail with E-PLACEHOLDER, pass once substituted ───────

_STARTER_TAG = {
    "def-of-ready.yaml": "sdlc/def-of-ready@1",
    "metric-library.yaml": "sdlc/metric-library@1",
    "standards.yaml": "sdlc/standards@1",
    "example-rubric.yaml": "sdlc/rubric@1",
}


def test_e_starters_are_born_red_then_green():
    for path in _starter_files():
        tag = _STARTER_TAG[path.name]
        schema = load_schema(tag)
        raw = path.read_text(encoding="utf-8")
        data, _ = miniyaml.load(raw)
        issues = validate(data, schema, file=path.name)
        assert "E-PLACEHOLDER" in _err_codes(issues), \
            f"{path.name} must ship red with a placeholder, got {issues}"
        fixed, _ = miniyaml.load(raw.replace("REPLACE-ME", "@org/example"))
        assert _err_codes(validate(fixed, schema, file=path.name)) == set(), \
            f"{path.name} must go green once placeholders are substituted"


# ── (g) meta anti-case: refuse an ill-formed schema ───────────────────

def test_g_unknown_keyword_schema_is_refused():
    bad = {"$id": "x@1", "type": "object", "made_up_keyword": 1,
           "properties": {"schema": {"const": "x@1", "x-consumer": "c"}}}
    try:
        load_schema(bad)
    except SchemaDefinitionError:
        return
    raise AssertionError("unknown schema keyword must be refused at load")


def test_g_consumerless_property_is_refused():
    bad = {"$id": "x@1", "type": "object",
           "properties": {"schema": {"const": "x@1"}}}
    try:
        load_schema(bad)
    except SchemaDefinitionError:
        return
    raise AssertionError("a property without x-consumer must be refused")


# ── (h) dev-CI differential: miniyaml == yaml.safe_load ───────────────

def test_h_miniyaml_matches_pyyaml_over_shipped_yaml():
    try:
        import yaml
    except ImportError:
        print("  SKIP  test_h (PyYAML absent)")
        return
    files = sorted(SHAPES.glob("*.yaml")) + _starter_files()
    for path in files:
        text = path.read_text(encoding="utf-8")
        mini, _ = miniyaml.load(text)
        ref = yaml.safe_load(text)
        assert mini == ref, f"miniyaml != yaml.safe_load for {path.name}"


# ── registry: KAPPA_FLOOR admissibility choke point ───────────────────

def test_registry_uncalibrated_rubric_is_inadmissible():
    rubric = {"schema": "sdlc/rubric@1", "id": "r", "version": 1,
              "prompt": "p", "scale": {"min": 0, "max": 4}, "threshold": 3,
              "criteria": [{"id": "c", "description": "one two three four"}]}
    bundle = {"rubrics": {("r", 1): rubric}, "tags_anti": set()}
    out = resolve_rubric("r@1", "judge-model", bundle)
    assert isinstance(out, Inadmissible), "draft rubric must not gate"


def test_registry_tampered_content_hash_is_inadmissible():
    from sdlc_schemas.registry import content_hash
    rubric = {"schema": "sdlc/rubric@1", "id": "r", "version": 1,
              "prompt": "p", "scale": {"min": 0, "max": 4}, "threshold": 3,
              "criteria": [{"id": "c", "description": "one two three four"}],
              "calibration": {"kappa": 0.9, "sample_size": 40,
                              "measured_at": "2026-06-30",
                              "binding": {"model_id": "judge-model",
                                          "content_hash": "0" * 64}},
              "meta_eval": {"probe_tag": "probes"}}
    bundle = {"rubrics": {("r", 1): rubric}, "tags_anti": {"probes"}}
    out = resolve_rubric("r@1", "judge-model", bundle)
    assert isinstance(out, Inadmissible), "tampered hash must be inadmissible"
    good = dict(rubric)
    good_cal = dict(rubric["calibration"])
    good_bind = dict(good_cal["binding"])
    good_bind["content_hash"] = content_hash(rubric)
    good_cal["binding"] = good_bind
    good["calibration"] = good_cal
    bundle["rubrics"][("r", 1)] = good
    resolved = resolve_rubric("r@1", "judge-model", bundle)
    assert not isinstance(resolved, Inadmissible)


def test_registry_kappa_floor_is_engine_constant():
    assert KAPPA_FLOOR == 0.80


# ── check_overlay: empty overlay fails closed (E-NO-FILES) ─────────────

def test_check_overlay_empty_is_no_files():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        report = check_overlay([tmp])
        assert report.ok is False
        assert report.files_checked == 0
        assert any(i.code == "E-NO-FILES" for i in report.issues)


def test_issues_to_findings_are_qg_shaped():
    issues = [SchemaIssue(code="E-REQUIRED", path="owner", message="missing",
                          file="f.yaml", line=3)]
    findings = issues_to_findings(issues)
    assert findings[0]["rule"] == "SCHEMA-E-REQUIRED"
    assert findings[0]["severity"] == "error"
    assert findings[0]["file"] == "f.yaml"


# ── adversarial-review fixes: overlay fails closed on broken instances ─

def _valid_instance_text(starter_name: str) -> str:
    raw = (STARTERS / starter_name).read_text(encoding="utf-8")
    return raw.replace("REPLACE-ME", "@org/example")


def _overlay(tmp: str, files: dict) -> None:
    for name, text in files.items():
        target = Path(tmp) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_overlay_unparseable_instance_is_e_syntax():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _overlay(tmp, {"standards.yaml": "schema: 'sdlc/standards@1'\nx: [1, 2]\n"})
        report = check_overlay([tmp])
        assert report.ok is False
        assert any(i.code == "E-SYNTAX" for i in report.issues), report.issues


def test_overlay_unknown_major_is_e_schema_tag():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _overlay(tmp, {"standards.yaml":
                       "schema: 'sdlc/standards@2'\nowner: '@org/x'\n"})
        report = check_overlay([tmp])
        assert report.ok is False
        assert any(i.code == "E-SCHEMA-TAG" for i in report.issues), report.issues


def test_overlay_broken_file_not_masked_by_valid_sibling():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _overlay(tmp, {
            "standards.yaml": _valid_instance_text("standards.yaml"),
            "bad.yaml": "schema: 'sdlc/stndards@1'\nowner: '@org/x'\n",
        })
        report = check_overlay([tmp])
        assert report.files_checked >= 1
        assert report.ok is False
        assert any(i.code == "E-SCHEMA-TAG" for i in report.issues), report.issues


# ── E-LINK-DUPLICATE + E-LINK-KIND are now reachable (were dead codes) ──

def test_link_duplicate_rubric_and_case_ids():
    loaded = [
        (Path("a.yaml"), {"schema": "sdlc/rubric@1", "id": "r", "version": 1}, {}),
        (Path("b.yaml"), {"schema": "sdlc/rubric@1", "id": "r", "version": 1}, {}),
        (Path("c.json"), {"schema": "sdlc/golden-case@1", "id": "x"}, {}),
        (Path("d.json"), {"schema": "sdlc/golden-case@1", "id": "x"}, {}),
    ]
    codes = [i.code for i in linkcheck.detect_duplicates(loaded)]
    assert codes == ["E-LINK-DUPLICATE", "E-LINK-DUPLICATE"], codes


def _probe_bundle(anti, allt):
    empty = frozenset()
    return {"rubrics": {}, "metrics": empty, "tags_anti": set(anti),
            "tags_all": set(allt), "case_ids": empty}


def test_link_kind_vs_unresolved_probe_tag():
    rubric = {"schema": "sdlc/rubric@1", "meta_eval": {"probe_tag": "smoke"}}
    args = (rubric, {}, "r.yaml", {})
    wrong_kind = linkcheck.check_links(*args, _probe_bundle([], ["smoke"]))
    assert [i.code for i in wrong_kind] == ["E-LINK-KIND"], wrong_kind
    ghost = linkcheck.check_links(*args, _probe_bundle([], []))
    assert [i.code for i in ghost] == ["E-LINK-UNRESOLVED"], ghost
    resolves = linkcheck.check_links(*args, _probe_bundle(["smoke"], ["smoke"]))
    assert resolves == [], resolves


# ── miniyaml matches the safe_load oracle or refuses (never mis-types) ──

_MINIYAML_MATCH = [
    ("1e3", "1e3"), ("1.5e3", "1.5e3"), ("1.5e-3", 0.0015), (".5", 0.5),
    ("5.", 5.0), ("3.14", 3.14), ("0", 0), ("7", 7), ("+7", 7), ("-3", -3),
    ("123", 123), ("0800", "0800"), ("abc", "abc"), ("v1", "v1"),
    ("1.2.3", "1.2.3"), ("2E3", "2E3"), ("true", True), ("false", False),
    ("null", None),
]
_MINIYAML_REFUSE = ["010", "007", "00", "0x10", "0b101", "1:30", "1_000",
                    "off", "on", "yes", "no", "OFF", ".inf", ".nan", "-.inf"]


def test_miniyaml_battery_matches_expected_types_and_values():
    for token, expected in _MINIYAML_MATCH:
        value = miniyaml.load(f"k: {token}\n")[0]["k"]
        vtype = type(value)
        assert vtype is type(expected) and value == expected, \
            f"{token!r} -> {value!r} ({vtype.__name__})"


def test_miniyaml_refuses_ambiguous_yaml11_scalars():
    for token in _MINIYAML_REFUSE:
        try:
            miniyaml.load(f"k: {token}\n")
        except miniyaml.MiniYAMLError as exc:
            assert exc.code == "E-SYNTAX", token
            continue
        raise AssertionError(f"{token!r} is YAML-1.1 ambiguous and must refuse")


def test_miniyaml_battery_agrees_with_oracle_when_available():
    try:
        import yaml
    except ImportError:
        print("  SKIP  oracle differential (PyYAML absent)")
        return
    for token, _ in _MINIYAML_MATCH:
        ref = yaml.safe_load(f"k: {token}")["k"]
        got = miniyaml.load(f"k: {token}\n")[0]["k"]
        assert type(got) is type(ref) and got == ref, f"{token}: {got!r} != {ref!r}"
    for token in _MINIYAML_REFUSE:
        ref = yaml.safe_load(f"k: {token}")["k"]
        assert not isinstance(ref, str), \
            f"{token}: oracle types as str, so refusing it is gratuitous"


# ── anchored pattern is full-match (a trailing newline cannot slip past) ─

def test_pattern_anchored_is_fullmatch_unanchored_is_search():
    assert shapecheck._pattern_matches(r"^[a-z]+$", "good")
    assert not shapecheck._pattern_matches(r"^[a-z]+$", "good\n")
    assert not shapecheck._pattern_matches(r"^[a-z]+$", "good\ninject")
    assert shapecheck._pattern_matches(r"(?i)rollback|kill.?switch",
                                       "we keep a rollback plan")


def test_pattern_trailing_newline_rejected_end_to_end():
    schema = load_schema("sdlc/golden-case@1")
    valid = iter_valid_cases(schema)[0]["instance"]
    assert _err_codes(validate(valid, schema, file="c")) == set()
    tampered = {**valid, "id": str(valid["id"]) + "\n"}
    got = validate(tampered, schema, file="c")
    assert "E-PATTERN" in _err_codes(got), got


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
        except Exception as e:  # noqa: BLE001 — runner surfaces every error
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
