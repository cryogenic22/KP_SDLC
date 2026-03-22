"""TDD spec for Data Contract & Schema Validation rules (DATA-*).

Data quality is the #1 failure mode in production AI systems.
These rules enforce schema validation on external data boundaries.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qg.checks_data_contracts import check_data_contracts


def _run(code: str) -> list[dict]:
    issues = []

    def add_issue(*, line, rule, severity, message, suggestion="", **kw):
        issues.append({"line": line, "rule": rule, "severity": severity, "message": message})

    lines = code.splitlines()
    check_data_contracts(file_path=Path("service.py"), content=code, lines=lines, add_issue=add_issue)
    return issues


# ── DATA-SCHEMA-NO-VALIDATION ────────────────────────────────────────


def test_flags_json_loads_without_validation():
    """json.loads on external data without Pydantic/schema validation → WARNING."""
    code = '''
import json
data = json.loads(response.text)
name = data["name"]
'''
    issues = _run(code)
    assert any(i["rule"] == "DATA-SCHEMA-NO-VALIDATION" for i in issues)


def test_flags_requests_json_without_validation():
    """response.json() without schema validation → WARNING."""
    code = '''
response = requests.get(url)
data = response.json()
process(data["items"])
'''
    issues = _run(code)
    assert any(i["rule"] == "DATA-SCHEMA-NO-VALIDATION" for i in issues)


def test_passes_with_pydantic_validation():
    """json.loads followed by Pydantic model → NOT flagged."""
    code = '''
import json
raw = json.loads(response.text)
data = UserModel.model_validate(raw)
'''
    issues = _run(code)
    assert not any(i["rule"] == "DATA-SCHEMA-NO-VALIDATION" for i in issues)


def test_passes_with_schema_validation():
    """json.loads with explicit schema validation → NOT flagged."""
    code = '''
import json
raw = json.loads(response.text)
validate(instance=raw, schema=user_schema)
'''
    issues = _run(code)
    assert not any(i["rule"] == "DATA-SCHEMA-NO-VALIDATION" for i in issues)


# ── DATA-RAW-DICT-ACCESS ────────────────────────────────────────────


def test_flags_raw_dict_access_on_api_response():
    """Direct dict["key"] on API response without .get() → WARNING."""
    code = '''
response = requests.get(api_url)
data = response.json()
user_id = data["user"]["id"]
'''
    issues = _run(code)
    assert any(i["rule"] == "DATA-RAW-DICT-ACCESS" for i in issues)


def test_passes_dict_get_on_api_response():
    """.get() on API response → NOT flagged."""
    code = '''
response = requests.get(api_url)
data = response.json()
user_id = data.get("user", {}).get("id")
'''
    issues = _run(code)
    assert not any(i["rule"] == "DATA-RAW-DICT-ACCESS" for i in issues)


# ── DATA-PIPELINE-NO-RETRY ──────────────────────────────────────────


def test_flags_celery_task_no_retry():
    """Celery task without retry config → WARNING."""
    code = '''
@app.task
def process_document(doc_id):
    result = heavy_computation(doc_id)
    return result
'''
    issues = _run(code)
    assert any(i["rule"] == "DATA-PIPELINE-NO-RETRY" for i in issues)


def test_passes_celery_task_with_retry():
    """Celery task with retry config → NOT flagged."""
    code = '''
@app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_document(self, doc_id):
    result = heavy_computation(doc_id)
    return result
'''
    issues = _run(code)
    assert not any(i["rule"] == "DATA-PIPELINE-NO-RETRY" for i in issues)


def test_flags_airflow_task_no_retry():
    """Airflow PythonOperator without retries → WARNING."""
    code = '''
task = PythonOperator(
    task_id="process",
    python_callable=process_data,
)
'''
    issues = _run(code)
    assert any(i["rule"] == "DATA-PIPELINE-NO-RETRY" for i in issues)


# ── No False Positives ───────────────────────────────────────────────


def test_no_flags_on_internal_json():
    """json.loads on internal config/file data → NOT flagged."""
    code = '''
import json
with open("config.json") as f:
    config = json.loads(f.read())
'''
    issues = _run(code)
    data_issues = [i for i in issues if i["rule"].startswith("DATA-")]
    assert len(data_issues) == 0


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
