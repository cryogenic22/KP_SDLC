"""G4 runtime-verify spine -- non-vacuous design tests.

Standalone-runnable: ``python -m pytest runtime-verify/tests/ -q``. Ships every
Loop-2 anti-case so no guard can silently regress: the grep-gate proves the
tolerance number lives only in the contract; the vacuous-artefact case proves an
empty dataset fails closed; the adapter-unresolved case proves absence is never
a skip; the tolerance-boundary cases pin the comparator (incl. relative with
a == 0 and a real one-ulp step); and the contract-dogfood case proves G4 runs
only on an E1.7-validated metric-library.
"""

from __future__ import annotations

import ast
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime-verify"))
sys.path.insert(0, str(ROOT / "schemas"))

from runtime_verify import (  # noqa: E402
    AdapterRegistry,
    AdapterUnresolved,
    CheckResult,
    ContractInvalid,
    Issue,
    Severity,
    StubAdapter,
    Tolerance,
    load_validated_library,
    reconcile,
    tolerance_of,
    within_tolerance,
)
from runtime_verify.cli import main as cli_main  # noqa: E402
from sdlc_schemas import issues_to_findings  # noqa: E402
from sdlc_schemas.errors import SchemaIssue  # noqa: E402

_PACK_DIR = ROOT / "runtime-verify" / "runtime_verify" / "packs"
_THRESHOLDS = ROOT / "runtime-verify" / "runtime_verify" / "thresholds.py"


# ── fixtures (tolerance/metric literals are legal here: the grep-gate scopes
#    only to pack + thresholds code) ───────────────────────────────────────

def _metric(system="stub", ref="ref.metric", tol_type="absolute", tol_value=0,
            grain=("date",), owner="@team/data"):
    return {
        "grain": list(grain),
        "source": {"system": system, "ref": ref},
        "owner": owner,
        "tolerance": {"type": tol_type, "value": tol_value},
    }


def _library(metrics=None, owner="@team/analytics"):
    return {
        "schema": "sdlc/metric-library@1",
        "owner": owner,
        "metrics": metrics if metrics is not None else {},
    }


def _registry(values):
    registry = AdapterRegistry()
    registry.register("stub", StubAdapter(values))
    return registry


# ── anti-case 1: grep-gate (no numeric literal in comparison position) ─────

_NUMERIC_CTORS = {"float", "int", "complex", "Decimal", "Fraction", "round"}


def _float_literals(tree):
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, float)]


def _nontrivial_int_literals(tree):
    # 0 and 1 are structural (counts, indices); any other int in check code is a
    # candidate magic number / hidden bound.
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, int)
            and not isinstance(n.value, bool) and n.value not in (0, 1)]


def _bool_in_compare(tree):
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            hits += [node.lineno for op in operands
                     if isinstance(op, ast.Constant) and isinstance(op.value, bool)]
    return hits


def _numeric_from_literal(tree):
    # float("0.05") / int("5") / Decimal("0.1") -- a number constructed from a
    # constant is still a hardcoded number.
    hits = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _NUMERIC_CTORS and node.args
                and isinstance(node.args[0], ast.Constant)):
            hits.append(node.lineno)
    return hits


def _smuggled_numbers(source):
    """Every way a compare number could hide in check code: a float literal, a
    non-trivial int literal, a bool in a comparison (``True == 1``), or a number
    constructed from a literal (``float('0.05')``). The detector must catch all
    of them or the grep-gate is theatre (adversarial review, Loop 2)."""
    tree = ast.parse(source)
    return sorted(_float_literals(tree) + _nontrivial_int_literals(tree)
                  + _bool_in_compare(tree) + _numeric_from_literal(tree))


def _pack_sources():
    files = sorted(_PACK_DIR.glob("*.py")) + [_THRESHOLDS]
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def test_grep_gate_catches_every_smuggling_form():
    # Positive controls: the natural ways a future dev reintroduces a hardcoded
    # tolerance. Each MUST be caught or the gate below is vacuous.
    bypasses = [
        "def f(x):\n    return x <= 0.05\n",              # direct float literal
        "def f(x):\n    t = 0.05\n    return x <= t\n",   # assign-then-compare
        "def f(x):\n    return x <= float('0.05')\n",     # constructed from literal
        "def f(x, b=0.05):\n    return x <= b\n",         # default argument
        "def f(x):\n    return x <= True\n",              # bool True == 1
        "def f(x):\n    return x <= (0.05,)[0]\n",        # tuple index
        "def f(x):\n    return x <= 5\n",                 # int literal in compare
    ]
    for src in bypasses:
        assert _smuggled_numbers(src), f"grep-gate missed a smuggled number: {src!r}"


def test_grep_gate_allows_structural_zero_and_one():
    # 0/1 are structural (counts, indices), never a tolerance -- must not trip.
    assert _smuggled_numbers("def f(xs):\n    n = 0\n    return xs[0], n > 1\n") == []


def test_no_hardcoded_number_in_check_code():
    sources = _pack_sources()
    assert len(sources) >= 2  # thresholds.py + at least one pack module
    for path, source in sources:
        hits = _smuggled_numbers(source)
        assert hits == [], f"{path.name} has a hardcoded number at lines {hits}"


# ── anti-case 2: vacuous artefact fails closed ─────────────────────────────

def test_empty_metric_set_fails_closed():
    result = reconcile(_library(metrics={}), _registry({}), {})
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "RV-NO-DATA" for issue in result.issues)


def test_checkresult_ok_requires_a_checked_metric():
    assert CheckResult(checked=0, skipped=0, issues=()).ok is False
    assert CheckResult(checked=1, skipped=0, issues=()).ok is True


def test_checkresult_ok_false_when_error_present_even_if_checked():
    err = Issue(rule="RV-X", severity=Severity.ERROR, message="m")
    assert CheckResult(checked=1, skipped=0, issues=(err,)).ok is False


# ── anti-case 3: adapter unresolved fails closed (never a skip) ─────────────

def test_unresolved_adapter_fails_closed_not_skipped():
    metrics = {"revenue_total": _metric(system="warehouse", ref="a.b.c")}
    result = reconcile(_library(metrics=metrics), _registry({}), {"revenue_total": 1})
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "RV-ADAPTER-UNRESOLVED" for issue in result.issues)


def test_registry_resolve_raises_on_unknown_system():
    try:
        AdapterRegistry().resolve("nope")
    except AdapterUnresolved:
        return
    raise AssertionError("resolve must fail closed on an unknown system")


def test_missing_authoritative_value_fails_closed():
    metrics = {"m": _metric(ref="absent.ref")}
    result = reconcile(_library(metrics=metrics), _registry({}), {"m": 1})
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "RV-NO-DATA" for issue in result.issues)


def test_missing_reported_value_fails_closed():
    metrics = {"m": _metric(ref="present.ref")}
    result = reconcile(_library(metrics=metrics), _registry({"present.ref": 10}), {})
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "RV-NO-DATA" for issue in result.issues)


def test_null_or_non_numeric_value_fails_closed_not_crash():
    metrics = {"m": _metric(ref="null.ref")}
    # a NULL (None) authoritative value -- the commonest SQL-warehouse signal --
    # must be a fail-closed RV-NO-DATA finding, never an uncaught TypeError.
    null_auth = reconcile(_library(metrics=metrics),
                          _registry({"null.ref": None}), {"m": 10})
    assert null_auth.ok is False
    assert any(issue.rule == "RV-NO-DATA" for issue in null_auth.issues)
    # a non-numeric reported value likewise fails closed, not crashes.
    bad_reported = reconcile(_library(metrics=metrics),
                             _registry({"null.ref": 10}), {"m": "N/A"})
    assert bad_reported.ok is False
    assert any(issue.rule == "RV-NO-DATA" for issue in bad_reported.issues)


# ── anti-case 4: tolerance boundary (absolute, relative, a == 0, one ulp) ───

def test_absolute_tolerance_exact_bound_passes_and_one_past_fails():
    tol = Tolerance(type="absolute", value=2)
    assert within_tolerance(102, 100, tol) is True   # diff 2 == bound
    assert within_tolerance(103, 100, tol) is False  # diff 3 > bound


def test_relative_tolerance_bound_and_one_ulp_step():
    tol = Tolerance(type="relative", value=0.005)   # bound = 0.005 * 1000 = 5.0
    assert within_tolerance(1005.0, 1000.0, tol) is True
    past = math.nextafter(1005.0, math.inf)
    assert within_tolerance(past, 1000.0, tol) is False


def test_relative_tolerance_with_zero_reference_base():
    tol = Tolerance(type="relative", value=0.01)     # bound collapses to 0 when a == 0
    assert within_tolerance(0, 0, tol) is True
    assert within_tolerance(1, 0, tol) is False


def test_tolerance_of_reads_the_number_only_from_the_contract():
    tol = tolerance_of(_metric(tol_type="relative", tol_value=0.02))
    assert tol.type == "relative"
    assert tol.value == 0.02


# ── end-to-end reconcile: pass, breach, owner target, shared finding shape ──

def test_reconcile_passes_within_tolerance_and_counts_checks():
    metrics = {
        "revenue_total": _metric(ref="rev", tol_type="relative", tol_value=0.01),
        "active_users": _metric(ref="users", tol_type="absolute", tol_value=0, grain=()),
    }
    registry = _registry({"rev": 1000.0, "users": 42})
    reported = {"revenue_total": 1005.0, "active_users": 42}
    result = reconcile(_library(metrics=metrics), registry, reported, contract_path="lib.yaml")
    assert result.ok is True
    assert result.checked == 2
    assert result.issues == ()


def test_reconcile_breach_is_counted_and_targets_the_owner():
    metrics = {"revenue_total": _metric(ref="rev", owner="@team/finance",
                                        tol_type="absolute", tol_value=0)}
    result = reconcile(_library(metrics=metrics), _registry({"rev": 1000}),
                       {"revenue_total": 1001}, contract_path="lib.yaml")
    assert result.ok is False
    assert result.checked == 1  # it WAS checked, and it breached
    breaches = [issue for issue in result.issues if issue.rule == "RV-RECONCILE-BREACH"]
    assert len(breaches) == 1
    assert breaches[0].owner == "@team/finance"


def test_to_finding_reuses_the_quality_gate_shape():
    issue = Issue(rule="RV-X", severity=Severity.ERROR, message="m", file="lib.yaml")
    finding = issue.to_finding()
    schema_finding = issues_to_findings(
        [SchemaIssue(code="E-SYNTAX", path="", message="m", file="f")]
    )[0]
    assert set(finding) == set(schema_finding)   # same reporting contract, not forked
    assert finding["severity"] == "error"
    assert finding["file"] == "lib.yaml"


# ── anti-case 5: contract dogfood via sdlc_schemas.resolve_instance/validate ─

_VALID_LIBRARY_YAML = (
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
)

# Same instance with the required `tolerance` removed -> E1.7 E-REQUIRED.
_INVALID_LIBRARY_YAML = (
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


def _write_core(tmp, text):
    core = Path(tmp) / ".sdlc-core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "metric-library.yaml").write_text(text, encoding="utf-8")
    return core


def test_valid_contract_loads_and_reconciles_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_LIBRARY_YAML)
        library, path = load_validated_library(core)
        result = reconcile(library, _registry({"rev.ref": 500}),
                           {"revenue_total": 500}, contract_path=str(path))
        assert result.ok is True
        assert result.checked == 1


def test_invalid_contract_is_refused_upstream():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _INVALID_LIBRARY_YAML)
        try:
            load_validated_library(core)
        except ContractInvalid as exc:
            rules = {finding["rule"] for finding in exc.findings}
            # pinned: the invalid library omits `tolerance` -> E1.7 E-REQUIRED,
            # not some unrelated failure that would make this anti-case vacuous.
            assert "SCHEMA-E-REQUIRED" in rules, rules
            return
        raise AssertionError("G4 must refuse to run on an E1.7-invalid contract")


def test_missing_contract_file_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_validated_library(Path(tmp) / ".sdlc-core")
        except FileNotFoundError:
            return
        raise AssertionError("a missing metric-library must fail closed")


# ── the CLI wires the spine end-to-end and honours the fail-closed exit code ─

def test_cli_reconcile_succeeds_with_fixtures():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_LIBRARY_YAML)
        fixtures = Path(tmp) / "fx.json"
        fixtures.write_text(json.dumps({
            "authoritative": {"rev.ref": 500},
            "reported": {"revenue_total": 500},
        }), encoding="utf-8")
        code = cli_main(["data", "reconcile", "--core-dir", str(core),
                         "--adapter", "stub", "--fixtures", str(fixtures)])
        assert code == 0


def test_cli_reconcile_fails_closed_on_unresolved_adapter():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_LIBRARY_YAML)
        code = cli_main(["data", "reconcile", "--core-dir", str(core),
                         "--adapter", "warehouse"])
        assert code == 1


def test_cli_fails_closed_on_missing_contract():
    with tempfile.TemporaryDirectory() as tmp:
        code = cli_main(["data", "reconcile", "--core-dir", str(tmp)])
        assert code == 1


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
