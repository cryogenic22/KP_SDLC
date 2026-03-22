"""CK-DATA-SCHEMA-DRIFT -- Schema Drift Detection.

Compares Pydantic model definitions against a baseline snapshot.
Flags breaking changes: removed fields, type changes, new required
fields without defaults, and removed models.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, List

from cathedral_keeper.models import Evidence, Finding


# -- Model Extraction --------------------------------------------------------


def extract_pydantic_models(code: str) -> dict:
    """Parse Python source code and extract Pydantic model definitions.

    Returns a dict mapping class_name -> {
        "fields": {
            field_name: {"type": str, "has_default": bool}
        }
    }

    Only classes inheriting from BaseModel (directly) are extracted.
    """
    tree = ast.parse(code)
    models: Dict[str, Any] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Check if any base is "BaseModel"
        is_pydantic = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "BaseModel":
                is_pydantic = True
                break
            if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                is_pydantic = True
                break
        if not is_pydantic:
            continue

        fields: Dict[str, Any] = {}
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                field_name = item.target.id
                field_type = _annotation_to_str(item.annotation)
                has_default = item.value is not None
                fields[field_name] = {
                    "type": field_type,
                    "has_default": has_default,
                }

        models[node.name] = {"fields": fields}

    return models


def _annotation_to_str(annotation: ast.expr) -> str:
    """Convert an AST annotation node to a readable string."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Constant):
        return str(annotation.value)
    if isinstance(annotation, ast.Attribute):
        return f"{_annotation_to_str(annotation.value)}.{annotation.attr}"
    if isinstance(annotation, ast.Subscript):
        value = _annotation_to_str(annotation.value)
        slice_val = _annotation_to_str(annotation.slice)
        return f"{value}[{slice_val}]"
    if isinstance(annotation, ast.Tuple):
        parts = [_annotation_to_str(e) for e in annotation.elts]
        return ", ".join(parts)
    # Fallback: use ast.dump
    return ast.dump(annotation)


# -- Schema Comparison -------------------------------------------------------


def compare_schemas(baseline: dict, current: dict) -> list[dict]:
    """Compare two model schema dicts and return a list of diffs.

    Detects:
    - model_removed: entire model in baseline but not in current
    - field_removed: field in baseline model but not in current model
    - type_changed: field type differs between baseline and current
    - required_field_added: new field in current without a default value
    """
    diffs: List[Dict[str, Any]] = []

    # Check for removed models
    for model_name in baseline:
        if model_name not in current:
            diffs.append({
                "model": model_name,
                "field": None,
                "change": "model_removed",
                "old_value": model_name,
                "new_value": None,
            })
            continue

        baseline_fields = baseline[model_name].get("fields", {})
        current_fields = current[model_name].get("fields", {})

        # Check for removed fields
        for field_name in baseline_fields:
            if field_name not in current_fields:
                diffs.append({
                    "model": model_name,
                    "field": field_name,
                    "change": "field_removed",
                    "old_value": baseline_fields[field_name]["type"],
                    "new_value": None,
                })
            else:
                # Check for type changes
                old_type = baseline_fields[field_name]["type"]
                new_type = current_fields[field_name]["type"]
                if old_type != new_type:
                    diffs.append({
                        "model": model_name,
                        "field": field_name,
                        "change": "type_changed",
                        "old_value": old_type,
                        "new_value": new_type,
                    })

        # Check for new required fields (in current but not in baseline)
        for field_name in current_fields:
            if field_name not in baseline_fields:
                if not current_fields[field_name]["has_default"]:
                    diffs.append({
                        "model": model_name,
                        "field": field_name,
                        "change": "required_field_added",
                        "old_value": None,
                        "new_value": current_fields[field_name]["type"],
                    })

    return diffs


# -- Full Policy Check -------------------------------------------------------


def check_schema_drift(
    baseline_models: dict,
    current_models: dict,
    file_path: str,
) -> list[Finding]:
    """Compare baseline and current Pydantic schemas, return CK Findings.

    If baseline_models is empty (first run), returns no findings.
    """
    if not baseline_models:
        return []

    diffs = compare_schemas(baseline_models, current_models)
    if not diffs:
        return []

    findings: List[Finding] = []
    for diff in diffs:
        change = diff["change"]
        model = diff["model"]
        field = diff.get("field")

        if change == "model_removed":
            title = f"Model '{model}' removed"
            snippet = f"Model {model} was present in baseline but is missing in current schema"
            severity = "high"
            fix = [
                f"Restore model '{model}' if removal was unintentional.",
                "If intentional, update the baseline snapshot.",
            ]
        elif change == "field_removed":
            title = f"Field '{model}.{field}' removed"
            snippet = f"Field {field} (type: {diff['old_value']}) was removed from {model}"
            severity = "high"
            fix = [
                f"Restore field '{field}' on model '{model}' if removal was unintentional.",
                "If intentional, update the baseline snapshot and migrate existing data.",
            ]
        elif change == "type_changed":
            title = f"Field '{model}.{field}' type changed: {diff['old_value']} -> {diff['new_value']}"
            snippet = f"Field {field} on {model} changed type from {diff['old_value']} to {diff['new_value']}"
            severity = "high"
            fix = [
                f"Revert field '{field}' type to '{diff['old_value']}' if unintentional.",
                "If intentional, add a data migration and update the baseline.",
            ]
        elif change == "required_field_added":
            title = f"New required field '{model}.{field}' added without default"
            snippet = f"New required field {field} (type: {diff['new_value']}) added to {model} without a default value"
            severity = "medium"
            fix = [
                f"Add a default value to field '{field}' to make it backward-compatible.",
                "If a required field is intentional, update the baseline and coordinate with consumers.",
            ]
        else:
            continue

        findings.append(Finding(
            policy_id="CK-DATA-SCHEMA-DRIFT",
            title=title,
            severity=severity,
            confidence="high",
            why_it_matters=(
                "Schema changes can break API consumers, corrupt serialized data, "
                "and cause runtime errors in downstream services."
            ),
            evidence=[
                Evidence(
                    file=file_path,
                    line=0,
                    snippet=snippet,
                    note=f"Change type: {change}",
                )
            ],
            fix_options=fix,
            verification=["Re-run schema drift check after fixing."],
            metadata={
                "model": model,
                "field": field,
                "change": change,
                "old_value": diff.get("old_value"),
                "new_value": diff.get("new_value"),
            },
        ))

    return findings
