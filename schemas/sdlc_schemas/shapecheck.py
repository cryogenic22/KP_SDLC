"""The instance validator + the shape-document meta-rules.

Two surfaces:

* ``meta_validate(doc)`` enforces the rules ON a shape document at load
  time — every keyword must be in the PINNED JSON-Schema subset (a silently
  ignored keyword IS vacuous validation), every declared property must carry
  an x-consumer (Epic-13 anti-bloat, machine-checked), the envelope ``schema``
  property must be pinned with ``const``, and the doc must ship >=1 valid and
  >=3 anti cases. Violations raise SchemaDefinitionError.

* ``validate_structural(instance, doc, ...)`` validates an INSTANCE against a
  shape. It never raises on a bad instance; it collects every issue. Scalar
  diagnoses short-circuit (a placeholder value reports E-PLACEHOLDER, not also
  the pattern miss it happens to trip) so each crafted anti-case pins exactly
  one code.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from .errors import SchemaDefinitionError, SchemaIssue

PINNED = frozenset({
    "type", "properties", "required", "additionalProperties", "items", "enum",
    "const", "pattern", "minimum", "maximum", "exclusiveMinimum", "minItems",
    "maxItems", "minLength", "minProperties", "uniqueItems", "propertyNames",
    "$defs", "$ref", "allOf", "if", "then", "title", "description",
    "$comment", "$id", "$schema",
})

_PLACEHOLDER = re.compile(r"^(TBD|TODO|CHANGE-ME|\?\?\?)$")


# ── meta-validation (rules on the shape document itself) ──────────────

def meta_validate(doc: dict) -> dict:
    """Refuse an ill-formed shape document. Returns ``doc`` when it is well
    formed so callers can chain."""
    _walk_schema(doc, in_conditional=False)
    _check_envelope_const(doc)
    _check_case_counts(doc)
    return doc


def _walk_schema(sub, in_conditional: bool) -> None:
    if not isinstance(sub, dict):
        return
    for key in sub:
        if key not in PINNED and not key.startswith("x-"):
            raise SchemaDefinitionError(f"unsupported schema keyword: {key!r}")
    _walk_properties(sub.get("properties", {}), in_conditional)
    for child in sub.get("$defs", {}).values():
        _walk_schema(child, in_conditional=False)
    _walk_child(sub.get("items"), in_conditional)
    _walk_child(sub.get("additionalProperties"), in_conditional)
    _walk_child(sub.get("propertyNames"), in_conditional)
    for clause in sub.get("allOf", []):
        _walk_schema(clause.get("if", {}), in_conditional=True)
        _walk_schema(clause.get("then", {}), in_conditional=True)
        if "if" not in clause:
            _walk_schema(clause, in_conditional)


def _walk_properties(props: dict, in_conditional: bool) -> None:
    for name, subschema in props.items():
        if (not in_conditional and isinstance(subschema, dict)
                and "$ref" not in subschema and "x-consumer" not in subschema):
            raise SchemaDefinitionError(
                f"property {name!r} has no x-consumer (META-MISSING-CONSUMER)")
        _walk_schema(subschema, in_conditional)


def _walk_child(child, in_conditional: bool) -> None:
    if isinstance(child, dict):
        _walk_schema(child, in_conditional)


def _check_envelope_const(doc: dict) -> None:
    schema_prop = doc.get("properties", {}).get("schema", {})
    if isinstance(schema_prop, dict) and "const" not in schema_prop:
        raise SchemaDefinitionError("envelope 'schema' property must be pinned "
                                    "with const")


def _check_case_counts(doc: dict) -> None:
    if len(doc.get("x-valid-cases", [])) < 1:
        raise SchemaDefinitionError("a shape must ship >=1 x-valid-case")
    if len(doc.get("x-anti-cases", [])) < 3:
        raise SchemaDefinitionError("a shape must ship >=3 x-anti-cases")


# ── instance validation ───────────────────────────────────────────────

@dataclass
class _Ctx:
    file: str
    lines: dict
    defs: dict
    issues: list = field(default_factory=list)


def validate_structural(instance, doc: dict, file: str = "",
                        lines: dict | None = None) -> list:
    ctx = _Ctx(file=file, lines=lines or {}, defs=doc.get("$defs", {}))
    _check(instance, doc, (), ctx)
    return ctx.issues


def _resolve(sub, ctx: _Ctx):
    if isinstance(sub, dict) and "$ref" in sub:
        return ctx.defs.get(sub["$ref"].split("/")[-1], {})
    return sub


def _check(value, sub, path: tuple, ctx: _Ctx) -> None:
    sub = _resolve(sub, ctx)
    if sub is True:
        return
    if sub is False:
        _emit(ctx, "E-FORBIDDEN", path, "field is not permitted here")
        return
    if _scalar_verdict(value, sub, path, ctx):
        return
    _check_typed(value, sub, path, ctx)


def _scalar_verdict(value, sub: dict, path: tuple, ctx: _Ctx) -> bool:
    """Short-circuit scalar checks; return True when the node is fully judged."""
    if (sub.get("x-forbid-placeholder") and isinstance(value, str)
            and _is_placeholder(value)):
        _emit(ctx, "E-PLACEHOLDER", path, f"placeholder value {value!r}")
        return True
    if "const" in sub and value != sub["const"]:
        _emit(ctx, "E-CONST", path, f"must equal {sub['const']!r}")
        return True
    if "enum" in sub and value not in sub["enum"]:
        _emit(ctx, "E-ENUM", path, f"{value!r} not in {sub['enum']}")
        return True
    if "type" in sub and not _type_ok(value, sub["type"]):
        _emit(ctx, "E-TYPE", path, f"expected type {sub['type']}")
        return True
    return False


def _check_typed(value, sub: dict, path: tuple, ctx: _Ctx) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        _check_range(value, sub, path, ctx)
    elif isinstance(value, str):
        _check_string(value, sub, path, ctx)
    elif isinstance(value, list):
        _check_array(value, sub, path, ctx)
    elif isinstance(value, dict):
        _check_object(value, sub, path, ctx)


def _check_range(value, sub: dict, path: tuple, ctx: _Ctx) -> None:
    mn, mx = sub.get("minimum"), sub.get("maximum")
    ex = sub.get("exclusiveMinimum")
    if (mn is not None and value < mn) or (mx is not None and value > mx) \
            or (ex is not None and value <= ex):
        _emit(ctx, "E-RANGE", path, f"{value} out of range")


def _check_string(value: str, sub: dict, path: tuple, ctx: _Ctx) -> None:
    ml = sub.get("minLength")
    if ml is not None and len(value) < ml:
        _emit(ctx, "E-MIN-LENGTH", path, f"shorter than {ml}")
        return
    pat = sub.get("pattern")
    if pat is not None and not _pattern_matches(pat, value):
        _emit(ctx, "E-PATTERN", path, f"{value!r} does not match {pat!r}")


def _check_array(value: list, sub: dict, path: tuple, ctx: _Ctx) -> None:
    mi, mx = sub.get("minItems"), sub.get("maxItems")
    if mi is not None and len(value) < mi:
        _emit(ctx, "E-MIN-ITEMS", path, f"fewer than {mi} items")
        return
    if mx is not None and len(value) > mx:
        _emit(ctx, "E-MAX-ITEMS", path, f"more than {mx} items")
        return
    if sub.get("uniqueItems") and _has_duplicates(value):
        _emit(ctx, "E-UNIQUE", path, "items are not unique")
    _check_unique_field(value, sub.get("x-unique-field"), path, ctx)
    items = sub.get("items")
    if items is not None:
        for idx, element in enumerate(value):
            _check(element, items, path + (idx,), ctx)


def _check_unique_field(value: list, field_name, path: tuple, ctx: _Ctx) -> None:
    if not field_name:
        return
    seen: set = set()
    for element in value:
        if isinstance(element, dict) and field_name in element:
            key = element[field_name]
            if key in seen:
                _emit(ctx, "E-UNIQUE-FIELD", path,
                      f"duplicate {field_name}={key!r}")
                return
            seen.add(key)


def _check_object(value: dict, sub: dict, path: tuple, ctx: _Ctx) -> None:
    mp = sub.get("minProperties")
    if mp is not None and len(value) < mp:
        _emit(ctx, "E-MIN-PROPS", path, f"fewer than {mp} properties")
        return
    for req in sub.get("required", []):
        if req not in value:
            _emit(ctx, "E-REQUIRED", path + (req,), f"missing required {req!r}")
    _check_members(value, sub, path, ctx)
    for clause in sub.get("allOf", []):
        _apply_clause(value, clause, path, ctx)


def _check_members(value: dict, sub: dict, path: tuple, ctx: _Ctx) -> None:
    props = sub.get("properties", {})
    addl = sub.get("additionalProperties", True)
    pnames = sub.get("propertyNames")
    for key, member in value.items():
        kpath = path + (key,)
        if _is_annotation_key(key):
            continue
        if (pnames and "pattern" in pnames
                and not _pattern_matches(pnames["pattern"], key)):
            _emit(ctx, "E-PATTERN", kpath, f"key {key!r} violates propertyNames")
            continue
        if key in props:
            _check(member, props[key], kpath, ctx)
        elif addl is False:
            _emit(ctx, "E-UNKNOWN-FIELD", kpath, f"unknown field {key!r}",
                  _did_you_mean(key, props))
        elif isinstance(addl, dict):
            _check(member, addl, kpath, ctx)


def _apply_clause(value: dict, clause: dict, path: tuple, ctx: _Ctx) -> None:
    if "if" not in clause:
        _check(value, clause, path, ctx)
        return
    if not _if_matches(value, clause["if"]):
        return
    then = clause.get("then", {})
    for req in then.get("required", []):
        if req not in value:
            _emit(ctx, "E-REQUIRED", path + (req,), f"missing required {req!r}")
    for name, subschema in then.get("properties", {}).items():
        if name in value:
            _check(value[name], subschema, path + (name,), ctx)


def _if_matches(value: dict, cond: dict) -> bool:
    for req in cond.get("required", []):
        if req not in value:
            return False
    for name, test in cond.get("properties", {}).items():
        if name not in value:
            continue
        if "const" in test and value[name] != test["const"]:
            return False
        if "enum" in test and value[name] not in test["enum"]:
            return False
    return True


# ── helpers ───────────────────────────────────────────────────────────

def _type_ok(value, typ) -> bool:
    types = typ if isinstance(typ, list) else [typ]
    return any(_one_type(value, t) for t in types)


def _one_type(value, t: str) -> bool:
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "null": value is None,
    }
    return checks.get(t, False)


def _is_placeholder(value: str) -> bool:
    return "REPLACE-ME" in value or bool(_PLACEHOLDER.match(value))


def _pattern_matches(pat: str, value: str) -> bool:
    """Apply a JSON-Schema ``pattern``. An author who fully anchors (^...$)
    means a full match; Python's ``re.search`` lets ``$`` match just before a
    trailing newline, so ``'good\\n'`` would slip past ``^[a-z]+$``. Use
    ``fullmatch`` for fully-anchored patterns (closing that hole) and ``search``
    for the rest, preserving the standard contains-semantics of an unanchored
    pattern (e.g. ``'(?i)rollback|kill.?switch'``)."""
    if pat.startswith("^") and pat.endswith("$") and not pat.endswith(r"\$"):
        return re.fullmatch(pat, value) is not None
    return re.search(pat, value) is not None


def _is_annotation_key(key: str) -> bool:
    return key.startswith("_") or key.startswith("x_")


def _has_duplicates(value: list) -> bool:
    seen: list = []
    for element in value:
        if element in seen:
            return True
        seen.append(element)
    return False


def _did_you_mean(key: str, props: dict) -> str:
    close = difflib.get_close_matches(key, list(props), n=1)
    return f"did you mean {close[0]!r}?" if close else ""


def _line(lines: dict, path: tuple) -> int:
    probe = path
    while probe:
        if probe in lines:
            return lines[probe]
        probe = probe[:-1]
    return lines.get((), 0)


def _emit(ctx: _Ctx, code: str, path: tuple, message: str, hint: str = "") -> None:
    ctx.issues.append(SchemaIssue(
        code=code, path="/".join(str(p) for p in path), message=message,
        file=ctx.file, line=_line(ctx.lines, path), hint=hint))
