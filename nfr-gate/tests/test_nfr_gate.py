"""G6 NFR-budget gate spine -- non-vacuous design tests.

Standalone-runnable: ``python -m pytest nfr-gate/tests/ -q``. Ships every Loop-5
anti-case so no guard can silently regress: the grep-gate proves the budget
number lives only in the contract; the vacuous-artefact case proves an empty
budget set fails closed; the unmeasured-budget case proves a declared-but-not-
observed NFR blocks (never a silent pass); the ceiling/floor boundary cases pin
the comparator in both directions; and the contract-dogfood case proves G6 runs
only on an E1.7-validated nfr-budget contract.

The grep-gate AST detectors are the same proven guard as G4's
(``runtime-verify``); each gate ships its own copy so the component stays
self-contained and the guard travels with the code it protects.
"""

from __future__ import annotations

import ast
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "nfr-gate"))
sys.path.insert(0, str(ROOT / "schemas"))

from nfr_gate import (  # noqa: E402
    Budget,
    CheckResult,
    ContractInvalid,
    Issue,
    Severity,
    budget_of,
    check_budgets,
    load_validated_budgets,
    within_budget,
)
from nfr_gate.cli import main as cli_main  # noqa: E402
from sdlc_schemas import issues_to_findings  # noqa: E402
from sdlc_schemas.errors import SchemaIssue  # noqa: E402

_PACK_DIR = ROOT / "nfr-gate" / "nfr_gate" / "packs"
_BUDGETS = ROOT / "nfr-gate" / "nfr_gate" / "budgets.py"


# ── fixtures (budget/limit literals are legal here: the grep-gate scopes only
#    to pack + budgets code) ─────────────────────────────────────────────────

def _budget_entry(limit=300, unit="ms", direction="max", owner="@team/api"):
    return {"limit": limit, "unit": unit, "direction": direction, "owner": owner}


def _contract(budgets=None, owner="@team/sre"):
    return {
        "schema": "sdlc/nfr-budget@1",
        "owner": owner,
        "budgets": budgets if budgets is not None else {},
    }


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
    constructed from a literal (``float('300')``). The detector must catch all of
    them or the grep-gate is theatre (adversarial review, Loop 2)."""
    tree = ast.parse(source)
    return sorted(_float_literals(tree) + _nontrivial_int_literals(tree)
                  + _bool_in_compare(tree) + _numeric_from_literal(tree))


def _pack_sources():
    files = sorted(_PACK_DIR.glob("*.py")) + [_BUDGETS]
    return [(path, path.read_text(encoding="utf-8")) for path in files]


def test_grep_gate_catches_every_smuggling_form():
    # Positive controls: the natural ways a future dev reintroduces a hardcoded
    # budget. Each MUST be caught or the gate below is vacuous.
    bypasses = [
        "def f(x):\n    return x <= 300\n",               # direct int literal
        "def f(x):\n    return x <= 300.0\n",             # direct float literal
        "def f(x):\n    t = 300\n    return x <= t\n",    # assign-then-compare
        "def f(x):\n    return x <= float('300')\n",      # constructed from literal
        "def f(x, b=300):\n    return x <= b\n",          # default argument
        "def f(x):\n    return x <= True\n",              # bool True == 1
        "def f(x):\n    return x <= (300,)[0]\n",         # tuple index
    ]
    for src in bypasses:
        assert _smuggled_numbers(src), f"grep-gate missed a smuggled number: {src!r}"


def test_grep_gate_allows_structural_zero_and_one():
    # 0/1 are structural (counts, indices), never a budget -- must not trip.
    assert _smuggled_numbers("def f(xs):\n    n = 0\n    return xs[0], n > 1\n") == []


def test_no_hardcoded_number_in_check_code():
    sources = _pack_sources()
    assert len(sources) >= 2  # budgets.py + at least one pack module
    for path, source in sources:
        hits = _smuggled_numbers(source)
        assert hits == [], f"{path.name} has a hardcoded number at lines {hits}"


# ── anti-case 2: vacuous artefact fails closed ─────────────────────────────

def test_empty_budget_set_fails_closed():
    result = check_budgets(_contract(budgets={}), {})
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "NFR-NO-BUDGETS" for issue in result.issues)


def test_checkresult_ok_requires_a_checked_budget():
    assert CheckResult(checked=0, skipped=0, issues=()).ok is False
    assert CheckResult(checked=1, skipped=0, issues=()).ok is True


def test_checkresult_ok_false_when_error_present_even_if_checked():
    err = Issue(rule="NFR-X", severity=Severity.ERROR, message="m")
    assert CheckResult(checked=1, skipped=0, issues=(err,)).ok is False


# ── anti-case 3: unmeasured budget fails closed (never a skip) ─────────────

def test_unmeasured_budget_fails_closed_not_skipped():
    budgets = {"api_p95_latency": _budget_entry()}
    result = check_budgets(_contract(budgets=budgets), {})  # no observation
    assert result.ok is False
    assert result.checked == 0
    assert any(issue.rule == "NFR-NO-OBSERVATION" for issue in result.issues)


def test_null_or_non_numeric_observation_fails_closed_not_crash():
    budgets = {"api_p95_latency": _budget_entry()}
    # a None observation (a missing measurement) must be a fail-closed
    # NFR-NO-OBSERVATION finding, never an uncaught TypeError on ``x <= None``.
    null_obs = check_budgets(_contract(budgets=budgets), {"api_p95_latency": None})
    assert null_obs.ok is False
    assert any(issue.rule == "NFR-NO-OBSERVATION" for issue in null_obs.issues)
    # a bool observation is not a real measurement either (True == 1 smuggling).
    bool_obs = check_budgets(_contract(budgets=budgets), {"api_p95_latency": True})
    assert bool_obs.ok is False
    assert any(issue.rule == "NFR-NO-OBSERVATION" for issue in bool_obs.issues)


def test_non_finite_or_negative_observation_fails_closed_both_directions():
    # Adversarial-review regression (Loop 5): the one-sided comparator would pass
    # -inf/-1 on a CEILING (green) and +inf on a FLOOR (green) -- a timeout,
    # overflow, or -1 "measurement failed" sentinel silently satisfying a budget.
    # Every non-finite/negative reading must fail closed as NFR-NO-OBSERVATION,
    # never a breach-by-luck and never a pass, in BOTH directions.
    ceiling = {"api_p95_latency": _budget_entry(limit=300, direction="max")}
    floor = {"service_availability": _budget_entry(limit=99.9, unit="percent",
                                                   direction="min")}
    unusable = (float("nan"), float("inf"), float("-inf"), -1)
    for observed in unusable:
        ceil_r = check_budgets(_contract(budgets=ceiling), {"api_p95_latency": observed})
        assert ceil_r.ok is False, f"ceiling passed unusable observation {observed!r}"
        assert ceil_r.checked == 0
        assert any(i.rule == "NFR-NO-OBSERVATION" for i in ceil_r.issues), observed
        floor_r = check_budgets(_contract(budgets=floor), {"service_availability": observed})
        assert floor_r.ok is False, f"floor passed unusable observation {observed!r}"
        assert any(i.rule == "NFR-NO-OBSERVATION" for i in floor_r.issues), observed


# ── anti-case 4: budget boundary (ceiling, floor, one ulp) ──────────────────

def test_ceiling_exact_bound_passes_and_one_past_fails():
    ceiling = Budget(limit=300, unit="ms", direction="max")
    assert within_budget(300, ceiling) is True    # observed == limit
    assert within_budget(301, ceiling) is False   # observed > limit


def test_floor_exact_bound_passes_and_one_under_fails():
    floor = Budget(limit=99.9, unit="percent", direction="min")
    assert within_budget(99.9, floor) is True     # observed == limit
    assert within_budget(99.8, floor) is False    # observed < limit


def test_ceiling_one_ulp_step():
    ceiling = Budget(limit=300.0, unit="ms", direction="max")
    assert within_budget(300.0, ceiling) is True
    past = math.nextafter(300.0, math.inf)
    assert within_budget(past, ceiling) is False


def test_budget_of_reads_the_number_only_from_the_contract():
    budget = budget_of(_budget_entry(limit=250, unit="mb", direction="max"))
    assert budget.limit == 250.0
    assert budget.unit == "mb"
    assert budget.direction == "max"


# ── end-to-end check: pass, breach, owner target, shared finding shape ──────

def test_check_passes_within_budget_and_counts_checks():
    budgets = {
        "api_p95_latency": _budget_entry(limit=300, direction="max"),
        "service_availability": _budget_entry(limit=99.9, unit="percent", direction="min"),
    }
    observations = {"api_p95_latency": 250, "service_availability": 99.95}
    result = check_budgets(_contract(budgets=budgets), observations, contract_path="nfr.yaml")
    assert result.ok is True
    assert result.checked == 2
    assert result.issues == ()


def test_ceiling_breach_is_counted_and_targets_the_owner():
    budgets = {"api_p95_latency": _budget_entry(limit=300, owner="@team/api", direction="max")}
    result = check_budgets(_contract(budgets=budgets), {"api_p95_latency": 500},
                           contract_path="nfr.yaml")
    assert result.ok is False
    assert result.checked == 1  # it WAS checked, and it breached
    breaches = [issue for issue in result.issues if issue.rule == "NFR-BUDGET-BREACH"]
    assert len(breaches) == 1
    assert breaches[0].owner == "@team/api"


def test_floor_breach_blocks():
    budgets = {"service_availability": _budget_entry(limit=99.9, unit="percent",
                                                     direction="min", owner="@team/sre")}
    result = check_budgets(_contract(budgets=budgets), {"service_availability": 99.0},
                           contract_path="nfr.yaml")
    assert result.ok is False
    assert result.checked == 1
    assert any(issue.rule == "NFR-BUDGET-BREACH" for issue in result.issues)


def test_to_finding_reuses_the_quality_gate_shape():
    issue = Issue(rule="NFR-X", severity=Severity.ERROR, message="m", file="nfr.yaml")
    finding = issue.to_finding()
    schema_finding = issues_to_findings(
        [SchemaIssue(code="E-SYNTAX", path="", message="m", file="f")]
    )[0]
    assert set(finding) == set(schema_finding)   # same reporting contract, not forked
    assert finding["severity"] == "error"
    assert finding["file"] == "nfr.yaml"


# ── anti-case 5: contract dogfood via sdlc_schemas.resolve_instance/validate ─

_VALID_NFR_YAML = (
    "schema: sdlc/nfr-budget@1\n"
    "owner: '@team/sre'\n"
    "budgets:\n"
    "  api_p95_latency:\n"
    "    limit: 300\n"
    "    unit: ms\n"
    "    direction: max\n"
    "    owner: '@team/api'\n"
)

# Same instance with the required `limit` removed -> E1.7 E-REQUIRED.
_INVALID_NFR_YAML = (
    "schema: sdlc/nfr-budget@1\n"
    "owner: '@team/sre'\n"
    "budgets:\n"
    "  api_p95_latency:\n"
    "    unit: ms\n"
    "    direction: max\n"
    "    owner: '@team/api'\n"
)


def _write_core(tmp, text):
    core = Path(tmp) / ".sdlc-core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "nfr-budget.yaml").write_text(text, encoding="utf-8")
    return core


def test_valid_contract_loads_and_checks_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        contract, path = load_validated_budgets(core)
        result = check_budgets(contract, {"api_p95_latency": 250}, contract_path=str(path))
        assert result.ok is True
        assert result.checked == 1


def test_invalid_contract_is_refused_upstream():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _INVALID_NFR_YAML)
        try:
            load_validated_budgets(core)
        except ContractInvalid as exc:
            rules = {finding["rule"] for finding in exc.findings}
            # pinned: the invalid contract omits `limit` -> E1.7 E-REQUIRED, not
            # some unrelated failure that would make this anti-case vacuous.
            assert "SCHEMA-E-REQUIRED" in rules, rules
            return
        raise AssertionError("G6 must refuse to run on an E1.7-invalid contract")


def test_missing_contract_file_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            load_validated_budgets(Path(tmp) / ".sdlc-core")
        except FileNotFoundError:
            return
        raise AssertionError("a missing nfr-budget contract must fail closed")


# ── the CLI wires the spine end-to-end and honours the exit-code contract ───

def test_cli_budget_succeeds_within_budget():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        obs = Path(tmp) / "obs.json"
        obs.write_text(json.dumps({"api_p95_latency": 250}), encoding="utf-8")
        code = cli_main(["nfr", "budget", "--core-dir", str(core),
                         "--observations", str(obs)])
        assert code == 0


def test_cli_budget_blocks_on_breach():
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        obs = Path(tmp) / "obs.json"
        obs.write_text(json.dumps({"api_p95_latency": 500}), encoding="utf-8")
        code = cli_main(["nfr", "budget", "--core-dir", str(core),
                         "--observations", str(obs)])
        assert code == 1


def test_cli_budget_blocks_when_unmeasured():
    # A declared budget with NO observations file is unmeasured -> exit 1 (block),
    # distinct from a config error. An unmeasured NFR is never a silent pass.
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        code = cli_main(["nfr", "budget", "--core-dir", str(core)])
        assert code == 1


def test_cli_blocks_on_non_finite_or_negative_observation():
    # json.loads accepts -Infinity/NaN by default, so a garbage reading reaches
    # the gate as a real float. A -1 failure sentinel and a -Infinity timeout
    # must BLOCK (exit 1), never pass a ceiling green (exit 0).
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        obs = Path(tmp) / "obs.json"
        for raw in ('{"api_p95_latency": -1}', '{"api_p95_latency": -Infinity}',
                    '{"api_p95_latency": NaN}'):
            obs.write_text(raw, encoding="utf-8")
            code = cli_main(["nfr", "budget", "--core-dir", str(core),
                             "--observations", str(obs)])
            assert code == 1, f"{raw} must block (exit 1), got {code}"


def test_cli_fails_closed_on_missing_contract():
    with tempfile.TemporaryDirectory() as tmp:
        code = cli_main(["nfr", "budget", "--core-dir", str(tmp)])
        assert code == 2


def test_cli_fails_closed_on_malformed_observations():
    # A given-but-broken observations file is a config error (exit 2), never
    # silently treated as "nothing measured".
    with tempfile.TemporaryDirectory() as tmp:
        core = _write_core(tmp, _VALID_NFR_YAML)
        obs = Path(tmp) / "obs.json"
        obs.write_text("{not json", encoding="utf-8")
        code = cli_main(["nfr", "budget", "--core-dir", str(core),
                         "--observations", str(obs)])
        assert code == 2


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
