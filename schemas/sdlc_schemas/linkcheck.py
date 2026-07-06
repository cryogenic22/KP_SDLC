"""The bundle link pass — referential integrity at CHECK time.

Structural validation proves one instance is well-shaped; this pass proves
the *bundle* hangs together: a rubric/metric/tag/layer reference resolves to a
real symbol (E-LINK-UNRESOLVED), cross-file keys are unique (E-LINK-DUPLICATE),
a probe tag lands on an actual anti-case (E-LINK-KIND), and the layer
may_import graph is a DAG (E-LINK-CYCLE). It also carries the loader-level
reserved-key rule (``eval.judge_kappa_floor`` -> E-RESERVED) and the rubric
scale/threshold cross-field check. It runs only over structurally-clean
instances, so each crafted anti-case pins exactly one code.
"""

from __future__ import annotations

from .errors import SchemaIssue
from .registry import parse_ref

RESERVED_CHECK_KEY = "eval.judge_kappa_floor"


def check_links(instance: dict, doc: dict, file: str, lines: dict,
                bundle: dict | None) -> list:
    """Run the loader/link checks appropriate to the instance's schema tag."""
    issues: list = []
    tag = instance.get("schema")
    if tag == "sdlc/standards@1":
        _reserved_key(instance, lines, file, issues)
    elif tag == "sdlc/rubric@1":
        _rubric_crossfield(instance, lines, file, issues)
        if bundle is not None:
            _rubric_links(instance, bundle, lines, file, issues)
    elif tag == "sdlc/architecture-contract@1":
        _architecture_links(instance, lines, file, issues)
    elif tag == "sdlc/def-of-ready@1" and bundle is not None:
        _def_of_ready_links(instance, bundle, lines, file, issues)
    elif tag == "sdlc/golden-case@1" and bundle is not None:
        _golden_links(instance, bundle, lines, file, issues)
    return issues


def build_bundle(instances: list) -> dict:
    """Assemble the symbol tables over a list of (tag, data) instances.
    ``tags_anti`` holds tags carried by an ACTIVE anti_case (a probe tag must
    land here to gate); ``tags_all`` holds every case tag, so a probe that
    resolves to a real-but-wrong-kind case is E-LINK-KIND, not -UNRESOLVED."""
    rubrics: dict = {}
    metrics: set = set()
    tags_anti: set = set()
    tags_all: set = set()
    case_ids: set = set()
    for tag, data in instances:
        if tag == "sdlc/rubric@1":
            rubrics[(data.get("id"), data.get("version"))] = data
        elif tag == "sdlc/metric-library@1":
            metrics |= set(data.get("metrics", {}))
        elif tag == "sdlc/golden-case@1":
            case_ids.add(data.get("id"))
            tags = set(data.get("tags", []))
            tags_all |= tags
            if data.get("kind") == "anti_case" and data.get("status") == "active":
                tags_anti |= tags
    return {"rubrics": rubrics, "metrics": metrics, "tags_anti": tags_anti,
            "tags_all": tags_all, "case_ids": case_ids}


def detect_duplicates(loaded: list) -> list:
    """Cross-file key uniqueness (E-LINK-DUPLICATE). Two rubric files sharing
    ``(id, version)`` or two golden-case files sharing an ``id`` would silently
    collapse the symbol table (last-write-wins) -- caught here so a bundle's
    keys are unique at CHECK time, not resolved by scan order. ``loaded`` is a
    list of ``(path, data, lines)``."""
    issues: list = []
    seen: dict = {}
    for path, data, lines in loaded:
        tag = data.get("schema")
        if tag == "sdlc/rubric@1":
            key = ("rubric", data.get("id"), data.get("version"))
            label = f"rubric {data.get('id')!r}@{data.get('version')}"
        elif tag == "sdlc/golden-case@1":
            key = ("case", data.get("id"))
            label = f"golden-case id {data.get('id')!r}"
        else:
            continue
        if key in seen:
            issues.append(SchemaIssue(
                code="E-LINK-DUPLICATE", path="id", file=str(path),
                line=lines.get(("id",), 0),
                message=f"{label} already defined in {seen[key]}"))
        else:
            seen[key] = str(path)
    return issues


def normalize_bundle(raw: dict | None) -> dict | None:
    """Turn a harness/fixture bundle ({rubrics:[{id,version}], ...}) into the
    canonical symbol-table shape check_links expects."""
    if raw is None:
        return None
    rubrics = {(r["id"], r["version"]): r for r in raw.get("rubrics", [])
               if isinstance(r, dict) and "id" in r and "version" in r}
    tags_anti = set(raw.get("tags_anti", []))
    return {
        "rubrics": rubrics,
        "metrics": set(raw.get("metrics", [])),
        "tags_anti": tags_anti,
        "tags_all": set(raw.get("tags_all", [])) | tags_anti,
        "case_ids": set(raw.get("case_ids", [])),
    }


# ── per-schema link rules ─────────────────────────────────────────────

def _reserved_key(instance: dict, lines, file, issues) -> None:
    if RESERVED_CHECK_KEY in instance.get("checks", {}):
        issues.append(_mk("E-RESERVED", ("checks", RESERVED_CHECK_KEY), lines,
                          file, f"{RESERVED_CHECK_KEY!r} is engine-reserved"))


def _rubric_crossfield(instance: dict, lines, file, issues) -> None:
    scale = instance.get("scale", {})
    theta = instance.get("threshold")
    lo, hi = scale.get("min"), scale.get("max")
    if None not in (lo, hi, theta) and not lo <= theta <= hi:
        issues.append(_mk("E-RANGE", ("threshold",), lines, file,
                          f"threshold {theta} outside scale [{lo}, {hi}]"))


def _rubric_links(instance: dict, bundle, lines, file, issues) -> None:
    probe = instance.get("meta_eval", {}).get("probe_tag")
    if not probe or probe in bundle["tags_anti"]:
        return
    path = ("meta_eval", "probe_tag")
    if probe in bundle.get("tags_all", set()):
        issues.append(_mk("E-LINK-KIND", path, lines, file,
                          f"probe tag {probe!r} resolves only to cases that are "
                          "not an active anti_case"))
    else:
        issues.append(_mk("E-LINK-UNRESOLVED", path, lines, file,
                          f"probe tag {probe!r} matches no case"))


def _def_of_ready_links(instance: dict, bundle, lines, file, issues) -> None:
    for kname, kind in instance.get("kinds", {}).items():
        judge = kind.get("sufficiency_judge") or {}
        ref = judge.get("rubric")
        if ref and parse_ref(ref) not in bundle["rubrics"]:
            issues.append(_mk("E-LINK-UNRESOLVED",
                              ("kinds", kname, "sufficiency_judge", "rubric"),
                              lines, file, f"rubric {ref!r} not in registry"))


def _golden_links(instance: dict, bundle, lines, file, issues) -> None:
    metric = instance.get("expected", {}).get("tolerance_metric")
    if metric and metric not in bundle["metrics"]:
        issues.append(_mk("E-LINK-UNRESOLVED", ("expected", "tolerance_metric"),
                          lines, file, f"metric {metric!r} not in library"))
    ref = instance.get("judge", {}).get("rubric")
    if ref and parse_ref(ref) not in bundle["rubrics"]:
        issues.append(_mk("E-LINK-UNRESOLVED", ("judge", "rubric"), lines, file,
                          f"rubric {ref!r} not in registry"))


def _architecture_links(instance: dict, lines, file, issues) -> None:
    layers = instance.get("layers", [])
    names = {ly.get("name") for ly in layers if isinstance(ly, dict)}
    _resolve_layer_refs(instance, layers, names, lines, file, issues)
    if not issues and _has_cycle(layers, names):
        issues.append(_mk("E-LINK-CYCLE", ("layers",), lines, file,
                          "may_import graph is not a DAG"))


def _resolve_layer_refs(instance, layers, names, lines, file, issues) -> None:
    for idx, layer in enumerate(layers):
        for jdx, target in enumerate(layer.get("may_import", [])):
            if target not in names:
                issues.append(_mk("E-LINK-UNRESOLVED",
                                  ("layers", idx, "may_import", jdx), lines,
                                  file, f"layer {target!r} is undeclared"))
    for idx, edge in enumerate(instance.get("forbidden", [])):
        for side in ("from", "to"):
            if edge.get(side) not in names:
                issues.append(_mk("E-LINK-UNRESOLVED", ("forbidden", idx, side),
                                  lines, file, f"layer {edge.get(side)!r} undeclared"))
    for idx, pair in enumerate(instance.get("independence", [])):
        for jdx, name in enumerate(pair):
            if name not in names:
                issues.append(_mk("E-LINK-UNRESOLVED",
                                  ("independence", idx, jdx), lines, file,
                                  f"layer {name!r} is undeclared"))


def _has_cycle(layers: list, names: set) -> bool:
    graph = {ly.get("name"): [m for m in ly.get("may_import", []) if m in names]
             for ly in layers if isinstance(ly, dict)}
    state: dict = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for nxt in graph.get(node, []):
            if state.get(nxt) == 1:
                return True
            if state.get(nxt) is None and visit(nxt):
                return True
        state[node] = 2
        return False

    return any(state.get(node) is None and visit(node) for node in graph)


def _mk(code: str, path: tuple, lines: dict, file: str, message: str) -> SchemaIssue:
    return SchemaIssue(code=code, path="/".join(str(p) for p in path),
                       message=message, file=file,
                       line=_line(lines, path))


def _line(lines: dict, path: tuple) -> int:
    probe = path
    while probe:
        if probe in lines:
            return lines[probe]
        probe = probe[:-1]
    return lines.get((), 0)
