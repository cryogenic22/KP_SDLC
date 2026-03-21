"""FEAT-005 — Tests for LLM-Output-Safety rule pack.

Detects unvalidated LLM output usage — the single most common source
of silent failure in agentic applications.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_llm_output_safety import check_llm_output_safety


def _run(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message})

    lines = code.splitlines()
    check_llm_output_safety(file_path=Path("app.py"), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── LLM-PY-UNVALIDATED-JSON ─────────────────────────────────────────


def test_flags_json_loads_on_llm_response():
    """json.loads() on LLM response without try/except → ERROR."""
    code = '''
response = client.chat.completions.create(messages=msgs)
data = json.loads(response.choices[0].message.content)
'''
    issues = _run(code)
    assert any(i["rule"] == "LLM-PY-UNVALIDATED-JSON" for i in issues)


def test_passes_json_loads_with_try_except():
    """json.loads() inside try/except → NOT flagged."""
    code = '''
response = client.chat.completions.create(messages=msgs)
try:
    data = json.loads(response.choices[0].message.content)
except json.JSONDecodeError:
    data = {}
'''
    issues = _run(code)
    assert not any(i["rule"] == "LLM-PY-UNVALIDATED-JSON" for i in issues)


# ── LLM-PY-DIRECT-EVAL ──────────────────────────────────────────────


def test_flags_eval_on_llm_output():
    """eval() on LLM-derived string → CRITICAL."""
    code = '''
result = llm.invoke(prompt)
computed = eval(result.content)
'''
    issues = _run(code)
    eval_issues = [i for i in issues if i["rule"] == "LLM-PY-DIRECT-EVAL"]
    assert len(eval_issues) >= 1
    assert eval_issues[0]["severity"] == "critical"


# ── LLM-PY-SILENT-FALLBACK ──────────────────────────────────────────


def test_flags_or_empty_dict_fallback():
    """`or {}` on LLM output → WARNING (empty looks like success)."""
    code = '''
response = chain.invoke(input_data)
result = response.get("output") or {}
'''
    issues = _run(code)
    assert any(i["rule"] == "LLM-PY-SILENT-FALLBACK" for i in issues)


def test_flags_or_empty_list_fallback():
    """`or []` on LLM output → WARNING."""
    code = '''
items = generate_items(prompt) or []
'''
    issues = _run(code)
    assert any(i["rule"] == "LLM-PY-SILENT-FALLBACK" for i in issues)


# ── LLM-PY-DICT-ACCESS-NO-GUARD ─────────────────────────────────────


def test_flags_direct_dict_access_on_llm_output():
    """Direct response["key"] on LLM dict without .get() → WARNING."""
    code = '''
response = chain.invoke({"query": q})
answer = response["answer"]
'''
    issues = _run(code)
    assert any(i["rule"] == "LLM-PY-DICT-ACCESS-NO-GUARD" for i in issues)


def test_passes_dict_get_on_llm_output():
    """.get() on LLM dict → NOT flagged."""
    code = '''
response = chain.invoke({"query": q})
answer = response.get("answer", "")
'''
    issues = _run(code)
    assert not any(i["rule"] == "LLM-PY-DICT-ACCESS-NO-GUARD" for i in issues)


# ── No False Positives ───────────────────────────────────────────────


def test_no_flags_on_normal_code():
    """Regular code without LLM calls should produce no LLM safety findings."""
    code = '''
import json

def process(data):
    result = json.loads(data)
    return result["key"]
'''
    issues = _run(code)
    llm_issues = [i for i in issues if i["rule"].startswith("LLM-PY")]
    assert len(llm_issues) == 0


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
