"""TDD spec for Schema Drift Detection.

Compares Pydantic models against a baseline snapshot. Flags breaking
changes: removed fields, type changes, new required fields without defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.policies.schema_drift import check_schema_drift, extract_pydantic_models, compare_schemas


# ── Model Extraction ─────────────────────────────────────────────────


def test_extract_pydantic_models_from_code():
    """Should extract class names, fields, and types from Pydantic models."""
    code = '''
from pydantic import BaseModel

class User(BaseModel):
    name: str
    email: str
    age: int = 0
'''
    models = extract_pydantic_models(code)
    assert "User" in models
    assert "name" in models["User"]["fields"]
    assert models["User"]["fields"]["name"]["type"] == "str"
    assert models["User"]["fields"]["age"]["has_default"] is True


def test_extract_multiple_models():
    """Should extract all Pydantic models from a file."""
    code = '''
from pydantic import BaseModel

class Request(BaseModel):
    query: str

class Response(BaseModel):
    answer: str
    confidence: float
'''
    models = extract_pydantic_models(code)
    assert len(models) == 2
    assert "Request" in models
    assert "Response" in models


def test_extract_ignores_non_pydantic():
    """Regular classes should NOT be extracted."""
    code = '''
class Helper:
    def run(self):
        pass

class Config(BaseModel):
    debug: bool
'''
    models = extract_pydantic_models(code)
    assert "Helper" not in models
    assert "Config" in models


# ── Schema Comparison ────────────────────────────────────────────────


def test_compare_detects_removed_field():
    """Removing a field from a model is a breaking change."""
    baseline = {"User": {"fields": {"name": {"type": "str", "has_default": False}, "email": {"type": "str", "has_default": False}}}}
    current = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}}
    diffs = compare_schemas(baseline, current)
    assert any(d["change"] == "field_removed" and d["field"] == "email" for d in diffs)


def test_compare_detects_type_change():
    """Changing a field's type is a breaking change."""
    baseline = {"User": {"fields": {"age": {"type": "int", "has_default": False}}}}
    current = {"User": {"fields": {"age": {"type": "str", "has_default": False}}}}
    diffs = compare_schemas(baseline, current)
    assert any(d["change"] == "type_changed" and d["field"] == "age" for d in diffs)


def test_compare_detects_new_required_field():
    """Adding a required field (no default) is a breaking change."""
    baseline = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}}
    current = {"User": {"fields": {"name": {"type": "str", "has_default": False}, "email": {"type": "str", "has_default": False}}}}
    diffs = compare_schemas(baseline, current)
    assert any(d["change"] == "required_field_added" and d["field"] == "email" for d in diffs)


def test_compare_allows_new_optional_field():
    """Adding a field WITH a default is NOT breaking."""
    baseline = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}}
    current = {"User": {"fields": {"name": {"type": "str", "has_default": False}, "age": {"type": "int", "has_default": True}}}}
    diffs = compare_schemas(baseline, current)
    breaking = [d for d in diffs if d["change"] in ("field_removed", "type_changed", "required_field_added")]
    assert len(breaking) == 0


def test_compare_detects_removed_model():
    """Removing an entire model is a breaking change."""
    baseline = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}, "Config": {"fields": {}}}
    current = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}}
    diffs = compare_schemas(baseline, current)
    assert any(d["change"] == "model_removed" and d["model"] == "Config" for d in diffs)


def test_compare_no_changes():
    """Identical schemas should produce no diffs."""
    schema = {"User": {"fields": {"name": {"type": "str", "has_default": False}}}}
    diffs = compare_schemas(schema, schema)
    assert len(diffs) == 0


# ── Full Policy Check ────────────────────────────────────────────────


def test_check_schema_drift_produces_findings():
    """Full check with baseline and current files should produce findings."""
    baseline_code = '''
from pydantic import BaseModel
class User(BaseModel):
    name: str
    email: str
    age: int
'''
    current_code = '''
from pydantic import BaseModel
class User(BaseModel):
    name: str
    age: str
'''
    findings = check_schema_drift(
        baseline_models=extract_pydantic_models(baseline_code),
        current_models=extract_pydantic_models(current_code),
        file_path="models.py",
    )
    assert len(findings) >= 2  # email removed + age type changed
    assert all(f.policy_id == "CK-DATA-SCHEMA-DRIFT" for f in findings)


def test_check_schema_drift_no_baseline():
    """No baseline = no drift findings (first run)."""
    current_code = '''
from pydantic import BaseModel
class User(BaseModel):
    name: str
'''
    findings = check_schema_drift(
        baseline_models={},
        current_models=extract_pydantic_models(current_code),
        file_path="models.py",
    )
    assert len(findings) == 0


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
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
