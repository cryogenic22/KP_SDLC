"""CK-DATA-SCHEMA-DRIFT -- Schema Drift Detection.

Compares Pydantic model definitions against a baseline snapshot.
Flags breaking changes: removed fields, type changes, new required
fields without defaults, and removed models.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
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


# -- Snapshot + Runner Wiring ------------------------------------------------


def _safe_rel(path: Path, root: Any) -> str:
    """Best-effort path relative to root, with forward slashes."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def capture_schemas(root: Any, files: List[Any]) -> Dict[str, Any]:
    """Snapshot Pydantic models for each file.

    Returns ``{file_rel: {model_name: {"fields": {...}}}}``. Files that
    cannot be read or parsed are skipped (a file with a syntax error has
    no extractable models — this is not silent data loss). Files with no
    Pydantic models are omitted to keep the snapshot small.
    """
    out: Dict[str, Any] = {}
    for f in files:
        try:
            code = Path(f).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            models = extract_pydantic_models(code)
        except SyntaxError:
            continue
        if not models:
            continue
        out[_safe_rel(Path(f), root)] = models
    return out


def _no_baseline_finding(rel: str, bpath: Path, *, status: str, reason: str) -> Finding:
    """Emit a single finding when no usable schema baseline is available.

    ``status`` distinguishes a genuinely missing baseline ("no_baseline")
    from one that exists but cannot be parsed ("baseline_unreadable"), so
    an operator is not told to run `ck baseline` when the real problem is a
    corrupt file.
    """
    unreadable = status == "baseline_unreadable"
    return Finding(
        policy_id="CK-DATA-SCHEMA-DRIFT",
        title="Schema baseline unreadable" if unreadable else "No schema baseline found",
        severity="low" if unreadable else "info",
        confidence="high",
        why_it_matters=(
            "Schema-drift detection requires a readable baseline snapshot of Pydantic "
            "models. "
            + (
                "The baseline file exists but could not be parsed; re-create it. "
                if unreadable
                else "Run `ck baseline` to capture one. "
            )
            + "Without it, breaking schema changes (removed fields, type changes) "
            "cannot be detected."
        ),
        evidence=[
            Evidence(file=rel, line=0, snippet=reason, note=f"Baseline path: {bpath}")
        ],
        fix_options=["Run `ck baseline --root .` to (re)capture the schema baseline."],
        verification=["ck baseline --root . && ck analyze --root ."],
        metadata={"baseline_path": rel, "status": status},
    )


def check_schema_drift_policy(
    *,
    root: Any,
    files: List[Any],
    baseline_path: Any,
) -> List[Finding]:
    """Runner-facing wrapper: compare current models to the baseline snapshot.

    Compares each scanned file's Pydantic models against that *same file's*
    entry in the baseline written by ``ck baseline``. This per-file
    comparison is independent of the order ``files`` are supplied in and is
    immune to same-named models in different files colliding — unlike a
    flat name-keyed merge.

    Files present in the baseline but not in the current scan (e.g. diff
    mode, or a file simply not passed) are skipped rather than reported as
    wholesale removals: this under-reports a deleted file's models but never
    fabricates a removal for a file we did not look at.

    When no usable baseline exists, emits a single finding so "drift
    detection has not run" is never confused with "no drift found"
    (conservation / no vacuous green).
    """
    bpath = Path(baseline_path)
    rel = _safe_rel(bpath, root)

    if not bpath.exists():
        return [_no_baseline_finding(rel, bpath, status="no_baseline",
                                     reason="(baseline file not found)")]

    try:
        baseline = json.loads(bpath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [_no_baseline_finding(rel, bpath, status="baseline_unreadable",
                                     reason=f"(baseline could not be read: {exc})")]

    baseline_schemas = (baseline or {}).get("schemas")
    if not baseline_schemas:
        return [_no_baseline_finding(rel, bpath, status="no_baseline",
                                     reason="(no 'schemas' section in baseline)")]

    current_schemas = capture_schemas(root, files)

    findings: List[Finding] = []
    for file_rel in sorted(current_schemas.keys()):
        base_models = baseline_schemas.get(file_rel) or {}
        if not base_models:
            continue  # new file: nothing in the baseline to compare against
        cur_models = current_schemas.get(file_rel) or {}
        findings.extend(check_schema_drift(base_models, cur_models, file_path=file_rel))
    return findings


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
