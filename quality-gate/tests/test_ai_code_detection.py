"""TDD spec for AI-Generated Code Detection + Teaching rules.

Detects unreviewed AI-generated code patterns AND provides actionable
guidance on how to generate better AI code. Each finding includes a
"right way" suggestion — the tool teaches through corrections.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_ai_code_quality import check_ai_code_quality


def _run(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message, "suggestion": suggestion})

    lines = code.splitlines()
    check_ai_code_quality(file_path=Path("module.py"), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── AI-PY-OVER-COMMENTING ───────────────────────────────────────────


def test_flags_comment_restating_code():
    """Comment that merely restates the next line → INFO."""
    code = '''
# Initialize the counter
counter = 0
# Increment the counter
counter += 1
# Return the counter
return counter
'''
    issues = _run(code)
    oc = [i for i in issues if i["rule"] == "AI-PY-OVER-COMMENTING"]
    assert len(oc) >= 2


def test_passes_meaningful_comment():
    """Comment explaining WHY, not WHAT → NOT flagged."""
    code = '''
# Rate limit requires exponential backoff per API docs section 4.2
delay = base_delay * (2 ** attempt)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AI-PY-OVER-COMMENTING" for i in issues)


def test_over_comment_suggestion_teaches():
    """Suggestion should teach the right pattern."""
    code = '''
# Set the value to 5
value = 5
'''
    issues = _run(code)
    oc = [i for i in issues if i["rule"] == "AI-PY-OVER-COMMENTING"]
    assert len(oc) >= 1
    assert "why" in oc[0]["suggestion"].lower() or "what" in oc[0]["suggestion"].lower()


# ── AI-PY-VERBOSE-NOOP-HANDLER ──────────────────────────────────────


def test_flags_except_just_raise():
    """except Exception as e: raise → WARNING (no-op handler)."""
    code = '''
try:
    process()
except Exception as e:
    raise
'''
    issues = _run(code)
    assert any(i["rule"] == "AI-PY-VERBOSE-NOOP-HANDLER" for i in issues)


def test_flags_except_just_pass():
    """except Exception: pass with a comment → WARNING."""
    code = '''
try:
    optional_cleanup()
except Exception:
    pass  # ignore errors
'''
    issues = _run(code)
    assert any(i["rule"] == "AI-PY-VERBOSE-NOOP-HANDLER" for i in issues)


def test_passes_except_with_logging():
    """except with actual handling (logging, retry) → NOT flagged."""
    code = '''
try:
    process()
except Exception as e:
    logger.error(f"Failed: {e}")
    metrics.increment("errors")
'''
    issues = _run(code)
    assert not any(i["rule"] == "AI-PY-VERBOSE-NOOP-HANDLER" for i in issues)


# ── AI-PY-EXCESSIVE-DOCSTRING ───────────────────────────────────────


def test_flags_docstring_longer_than_body():
    """Docstring with more lines than the function body → INFO."""
    code = '''
def add(a, b):
    """Add two numbers together.

    This function takes two numeric arguments and returns their sum.
    It supports integers, floats, and any other numeric type that
    implements the __add__ method.

    Args:
        a: The first number to add.
        b: The second number to add.

    Returns:
        The sum of a and b.
    """
    return a + b
'''
    issues = _run(code)
    assert any(i["rule"] == "AI-PY-EXCESSIVE-DOCSTRING" for i in issues)


def test_passes_proportional_docstring():
    """Docstring shorter than body → NOT flagged."""
    code = '''
def process_invoice(invoice_data, rules):
    """Apply validation rules to invoice and return enriched result."""
    validated = validate_schema(invoice_data)
    enriched = apply_business_rules(validated, rules)
    total = calculate_totals(enriched)
    enriched["total"] = total
    enriched["status"] = "processed"
    return enriched
'''
    issues = _run(code)
    assert not any(i["rule"] == "AI-PY-EXCESSIVE-DOCSTRING" for i in issues)


# ── AI-PY-REDUNDANT-TYPE-CHECK ──────────────────────────────────────


def test_flags_isinstance_on_typed_param():
    """isinstance check on a type-hinted parameter → INFO."""
    code = '''
def process(items: list[str]) -> int:
    if not isinstance(items, list):
        raise TypeError("items must be a list")
    return len(items)
'''
    issues = _run(code)
    assert any(i["rule"] == "AI-PY-REDUNDANT-TYPE-CHECK" for i in issues)


def test_passes_isinstance_on_untyped_param():
    """isinstance on untyped param → NOT flagged (validation is reasonable)."""
    code = '''
def process(items):
    if not isinstance(items, list):
        raise TypeError("items must be a list")
    return len(items)
'''
    issues = _run(code)
    assert not any(i["rule"] == "AI-PY-REDUNDANT-TYPE-CHECK" for i in issues)


# ── AI-PY-GENERIC-NAMES ─────────────────────────────────────────────


def test_flags_many_generic_names():
    """Multiple generic variable names in one function → INFO."""
    code = '''
def handle_request():
    data = get_data()
    result = process(data)
    temp = transform(result)
    output = format(temp)
    return output
'''
    issues = _run(code)
    assert any(i["rule"] == "AI-PY-GENERIC-NAMES" for i in issues)


def test_passes_domain_names():
    """Domain-specific variable names → NOT flagged."""
    code = '''
def process_invoice():
    invoice = fetch_invoice()
    line_items = extract_items(invoice)
    subtotal = sum(item.amount for item in line_items)
    return subtotal
'''
    issues = _run(code)
    assert not any(i["rule"] == "AI-PY-GENERIC-NAMES" for i in issues)


# ── No False Positives ───────────────────────────────────────────────


def test_no_flags_on_clean_code():
    """Well-written code → no AI detection flags."""
    code = '''
def calculate_shipping_cost(weight_kg: float, distance_km: float) -> float:
    """Compute cost using zone-based rate table."""
    zone = _lookup_zone(distance_km)
    base_rate = ZONE_RATES[zone]
    # Surcharge for heavy packages per carrier contract amendment 2024-Q3
    surcharge = 0.15 * weight_kg if weight_kg > 30 else 0
    return base_rate * weight_kg + surcharge
'''
    issues = _run(code)
    ai_issues = [i for i in issues if i["rule"].startswith("AI-PY")]
    assert len(ai_issues) == 0


# ── Teaching: All suggestions present ────────────────────────────────


def test_all_rules_have_teaching_suggestions():
    """Every AI-PY finding must include a suggestion that teaches the right pattern."""
    code = '''
# Set x to 1
x = 1
def foo(items: list):
    """Process items.

    This function processes the given items list.
    It iterates over each item and processes it.

    Args:
        items: List of items.

    Returns:
        Processed items.
    """
    if not isinstance(items, list):
        raise TypeError("must be list")
    data = get_data()
    result = process(data)
    temp = transform(result)
    output = format(temp)
    try:
        risky()
    except Exception as e:
        raise
    return output
'''
    issues = _run(code)
    ai_issues = [i for i in issues if i["rule"].startswith("AI-PY")]
    assert len(ai_issues) >= 3
    for issue in ai_issues:
        assert len(issue["suggestion"]) > 10, f"{issue['rule']} missing teaching suggestion"


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
