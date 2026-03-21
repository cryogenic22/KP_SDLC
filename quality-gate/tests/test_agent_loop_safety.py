"""FEAT-007 — Tests for Agent-Loop-Safety rule pack.

Detects unbounded agent loops — production time-bombs that work in
testing but fail expensively in production.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_agent_loops import check_agent_loop_safety


def _run(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message})

    lines = code.splitlines()
    check_agent_loop_safety(file_path=Path("agent.py"), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── LOOP-PY-WHILE-TRUE-LLM ──────────────────────────────────────────


def test_flags_while_true_with_llm():
    """while True + LLM call without break → CRITICAL."""
    code = '''
while True:
    response = llm.invoke(prompt)
    process(response)
'''
    issues = _run(code)
    wt = [i for i in issues if i["rule"] == "LOOP-PY-WHILE-TRUE-LLM"]
    assert len(wt) >= 1
    assert wt[0]["severity"] == "critical"


def test_passes_while_true_with_break():
    """while True + LLM + break within body → NOT flagged."""
    code = '''
while True:
    response = llm.invoke(prompt)
    if response.done:
        break
'''
    issues = _run(code)
    wt = [i for i in issues if i["rule"] == "LOOP-PY-WHILE-TRUE-LLM"]
    assert len(wt) == 0


# ── LOOP-PY-NO-MAX-ITERATIONS ───────────────────────────────────────


def test_flags_for_loop_llm_no_max():
    """Loop with LLM call but no iteration counter → ERROR."""
    code = '''
for item in items:
    result = chain.invoke({"input": item})
    results.append(result)
'''
    issues = _run(code)
    nmi = [i for i in issues if i["rule"] == "LOOP-PY-NO-MAX-ITERATIONS"]
    assert len(nmi) >= 1


def test_passes_loop_with_max_check():
    """Loop with LLM + explicit max check → NOT flagged."""
    code = '''
for i, item in enumerate(items[:MAX_ITERATIONS]):
    result = chain.invoke({"input": item})
    results.append(result)
'''
    issues = _run(code)
    nmi = [i for i in issues if i["rule"] == "LOOP-PY-NO-MAX-ITERATIONS"]
    assert len(nmi) == 0


# ── LOOP-PY-LANGGRAPH-UNBOUNDED ─────────────────────────────────────


def test_flags_stategraph_no_recursion_limit():
    """StateGraph without recursion_limit → ERROR."""
    code = '''
graph = StateGraph(AgentState)
graph.add_node("agent", call_model)
graph.add_edge("agent", "tools")
app = graph.compile()
'''
    issues = _run(code)
    lg = [i for i in issues if i["rule"] == "LOOP-PY-LANGGRAPH-UNBOUNDED"]
    assert len(lg) >= 1


def test_passes_stategraph_with_recursion_limit():
    """StateGraph with recursion_limit → NOT flagged."""
    code = '''
graph = StateGraph(AgentState)
graph.add_node("agent", call_model)
app = graph.compile(recursion_limit=25)
'''
    issues = _run(code)
    lg = [i for i in issues if i["rule"] == "LOOP-PY-LANGGRAPH-UNBOUNDED"]
    assert len(lg) == 0


# ── No False Positives ───────────────────────────────────────────────


def test_no_flags_on_normal_loops():
    """Regular loops without LLM calls should not be flagged."""
    code = '''
for item in items:
    result = process(item)
    results.append(result)
'''
    issues = _run(code)
    loop_issues = [i for i in issues if i["rule"].startswith("LOOP-PY")]
    assert len(loop_issues) == 0


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
