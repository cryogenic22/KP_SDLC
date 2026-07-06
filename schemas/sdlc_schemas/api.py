"""Public API: load, validate, resolve, and gate-consumption glue.

``validate`` never raises on a bad instance — it collects every structural
issue, and only when the instance is structurally clean does it run the
loader/link pass (a dangling reference is meaningless if the shape is already
wrong). ``check_overlay`` fails closed on an empty overlay (E-NO-FILES): a
missing overlay is a distinct hard failure, never an absence of findings.
``issues_to_findings`` renders issues in the quality-gate finding shape so
schema failures flow through the existing report pipeline.
"""

from __future__ import annotations

import importlib.resources as resources
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import linkcheck, miniyaml, shapecheck
from .errors import SchemaIssue
from .registry import KNOWN, dispatch

_SINGLETON_INSTANCE = {
    "sdlc/def-of-ready@1": "def-of-ready.yaml",
    "sdlc/metric-library@1": "metric-library.yaml",
    "sdlc/standards@1": "standards.yaml",
    "sdlc/architecture-contract@1": "architecture.yaml",
}


@dataclass(frozen=True)
class Schema:
    """A meta-validated shape document plus its tag."""

    tag: str
    doc: dict


@dataclass
class Report:
    ok: bool
    files_checked: int
    issues: list = field(default_factory=list)


def load_document(path):
    """Parse a YAML or JSON document -> (data, lines). JSON carries no line
    map (best-effort 0)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text), {}
    return miniyaml.load(text)


def _load_shape(tag: str) -> dict:
    filename = dispatch(tag)
    text = (resources.files("sdlc_schemas").joinpath("shapes", filename)
            .read_text(encoding="utf-8"))
    if filename.endswith(".json"):
        return json.loads(text)
    data, _ = miniyaml.load(text)
    return data


def load_schema(tag_or_doc) -> Schema:
    """Meta-validate and wrap a shape. Accepts a known tag, a path, or an
    inline schema dict (for meta tests)."""
    if isinstance(tag_or_doc, dict):
        doc = shapecheck.meta_validate(tag_or_doc)
        return Schema(tag=doc.get("$id", ""), doc=doc)
    if tag_or_doc in KNOWN:
        doc = shapecheck.meta_validate(_load_shape(tag_or_doc))
        return Schema(tag=tag_or_doc, doc=doc)
    data, _ = load_document(tag_or_doc)
    doc = shapecheck.meta_validate(data)
    return Schema(tag=doc.get("$id", ""), doc=doc)


def _doc_of(schema) -> dict:
    return schema.doc if isinstance(schema, Schema) else schema


def validate(instance, schema, file: str = "", lines: dict | None = None,
             bundle: dict | None = None) -> list:
    """Collect every issue for ``instance``. Structural checks run first and
    exhaustively; the loader/link pass runs only if the shape is clean."""
    doc = _doc_of(schema)
    lines = lines or {}
    issues = shapecheck.validate_structural(instance, doc, file, lines)
    if any(i.severity == "error" for i in issues):
        return issues
    issues += linkcheck.check_links(instance, doc, file, lines,
                                    linkcheck.normalize_bundle(bundle))
    return issues


def iter_valid_cases(schema) -> list:
    return list(_doc_of(schema).get("x-valid-cases", []))


def iter_anti_cases(schema) -> list:
    return list(_doc_of(schema).get("x-anti-cases", []))


def issues_to_findings(issues: list) -> list:
    """Render issues as quality-gate findings ({rule: 'SCHEMA-'+code, ...})."""
    return [
        {
            "rule": "SCHEMA-" + issue.code,
            "severity": issue.severity,
            "file": issue.file,
            "line": issue.line,
            "message": issue.message,
        }
        for issue in issues
    ]


def resolve_instance(tag: str, roots):
    """Resolve a singleton contract instance from the overlay roots,
    fail-closed on unknown major and missing file."""
    filename = _SINGLETON_INSTANCE.get(tag)
    if filename is None:
        raise ValueError(f"{tag!r} is not a resolvable singleton instance")
    for root in roots:
        candidate = Path(root) / filename
        if candidate.exists():
            data, _ = load_document(candidate)
            return data, candidate
    raise FileNotFoundError(f"no {filename} under {list(roots)}")


def check_overlay(roots) -> Report:
    """Validate every overlay instance and its bundle links. Fails closed
    (E-NO-FILES) only when the overlay genuinely contains no instance files;
    a file that declares an instance envelope but cannot be parsed
    (E-SYNTAX) or names an undispatchable tag (E-SCHEMA-TAG) is a hard failure,
    never a silent drop."""
    loaded, gathered = _gather_instances(roots)
    if not loaded and not gathered:
        issue = SchemaIssue(code="E-NO-FILES", path="", message=(
            "overlay contains no schema instances"))
        return Report(ok=False, files_checked=0, issues=[issue])
    issues = gathered + _validate_loaded(loaded)
    ok = not any(i.severity == "error" for i in issues)
    return Report(ok=ok, files_checked=len(loaded), issues=issues)


def _gather_instances(roots):
    """Return ``(loaded, issues)``. A parse or dispatch failure on a file that
    declares itself an instance is converted to a fail-closed SchemaIssue
    rather than swallowed, so a corrupt or future-major overlay file cannot
    vanish from the gate."""
    loaded: list = []
    issues: list = []
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix in (".yaml", ".yml", ".json") and path.is_file():
                _maybe_instance(path, loaded, issues)
    return loaded, issues


def _maybe_instance(path: Path, loaded: list, issues: list) -> None:
    rel = str(path)
    try:
        data, lines = load_document(path)
    except miniyaml.MiniYAMLError as exc:
        issues.append(SchemaIssue(
            code="E-SYNTAX", path="", file=rel, line=getattr(exc, "line", 0),
            message=getattr(exc, "message", str(exc))))
        return
    except (json.JSONDecodeError, ValueError) as exc:
        issues.append(SchemaIssue(
            code="E-SYNTAX", path="", file=rel,
            message=f"unparseable instance: {exc}"))
        return
    if not isinstance(data, dict) or "schema" not in data:
        return  # an incidental (non-instance) overlay file: it declares no tag
    tag = data.get("schema")
    if tag not in KNOWN:
        issues.append(SchemaIssue(
            code="E-SCHEMA-TAG", path="schema", file=rel,
            line=lines.get(("schema",), 0),
            message=f"unknown or unshipped schema tag: {tag!r}"))
        return
    loaded.append((path, data, lines))


def _validate_loaded(loaded: list) -> list:
    issues: list = list(linkcheck.detect_duplicates(loaded))
    bundle = linkcheck.build_bundle([(d.get("schema"), d) for _, d, _ in loaded])
    for path, data, lines in loaded:
        doc = load_schema(data["schema"]).doc
        structural = shapecheck.validate_structural(data, doc, str(path), lines)
        issues += structural
        if not any(i.severity == "error" for i in structural):
            issues += linkcheck.check_links(data, doc, str(path), lines, bundle)
    return issues
