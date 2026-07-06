"""Corpus loader: discover, E1.7-validate, and stage golden-case instances.

Only ``status == active`` cases execute. Every case is validated against
``sdlc/golden-case@1`` through ``sdlc_schemas`` before it can run, and a
cross-file id collision is caught too; ANY invalid instance aborts the load
(CorpusInvalid), so a malformed case is refused UPSTREAM, never silently
skipped -- the contract-dogfood tenet, mirroring G4's ``ContractInvalid``.
Rubrics and the metric-library are resolved and validated alongside so the
judge choke and golden compares have a real symbol bundle to resolve against.
A corpus that resolves ZERO active cases is not raised here: the run engine
turns it into a fail-closed non-green (EE-NO-ACTIVE-CASES), so ``ee run`` still
emits a scorecard reflecting the empty scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sdlc_schemas import (
    issues_to_findings,
    load_document,
    load_schema,
    resolve_instance,
    validate,
)
from sdlc_schemas.linkcheck import build_bundle, detect_duplicates

_GOLDEN_CASE_TAG = "sdlc/golden-case@1"
_RUBRIC_TAG = "sdlc/rubric@1"
_METRIC_LIBRARY_TAG = "sdlc/metric-library@1"
_ACTIVE = "active"
_ERROR = "error"
_CASE_GLOB = "*.case.json"
_RUBRIC_GLOB = "*.yaml"


class CorpusInvalid(Exception):
    """A corpus instance fails E1.7 validation; the engine refuses to run.

    An unvalidated corpus never executes, so a malformed case cannot
    masquerade as an absence of findings (fail closed upstream).
    """

    def __init__(self, findings) -> None:
        self.findings = list(findings)
        super().__init__(
            f"corpus is invalid ({len(self.findings)} issue(s)); "
            "ee refuses to run on an unvalidated corpus"
        )


@dataclass(frozen=True)
class LoadedCorpus:
    """The validated run set plus the symbol bundle and metric tolerances the
    kinds resolve against."""

    active_cases: tuple
    all_cases: tuple
    bundle: dict
    metrics: dict
    corpus_root: Path


def load_corpus(core_dir, corpus_dir=None) -> LoadedCorpus:
    """Load, validate, and stage the corpus under an overlay dir.

    ``core_dir`` holds the overlay (rubrics, metric-library); the corpus lives
    at ``corpus_dir`` or ``<core_dir>/corpus`` by default. Raises
    ``CorpusInvalid`` on any E1.7 error so an unvalidated corpus never runs.
    """
    core = Path(core_dir)
    corpus_root = Path(corpus_dir) if corpus_dir else core / "corpus"
    cases = _load_documents(corpus_root, _CASE_GLOB, recursive=True)
    rubrics = _load_documents(core / "rubrics", _RUBRIC_GLOB, recursive=False)
    library = _load_metric_library(core)
    _refuse_if_invalid(cases, rubrics, library)
    case_data = [data for _, data, _ in cases]
    rubric_data = [data for _, data, _ in rubrics]
    bundle = _build_bundle(case_data, rubric_data, library)
    active = tuple(case for case in case_data if case.get("status") == _ACTIVE)
    return LoadedCorpus(
        active_cases=active,
        all_cases=tuple(case_data),
        bundle=bundle,
        metrics=(library or {}).get("metrics", {}),
        corpus_root=corpus_root,
    )


def _pair(path):
    data, lines = load_document(path)
    return path, data, lines


def _load_documents(directory, glob, *, recursive):
    """Return ``[(path, data, lines)]`` for every matching instance file, or an
    empty list when the directory is absent (handled fail-closed downstream)."""
    base = Path(directory)
    if not base.exists():
        return []
    paths = sorted(base.rglob(glob)) if recursive else sorted(base.glob(glob))
    return [_pair(path) for path in paths]


def _load_metric_library(core):
    """Resolve the optional metric-library instance; ``None`` when absent. A
    golden compare that needs its tolerance fails closed later if it is missing."""
    try:
        data, _ = resolve_instance(_METRIC_LIBRARY_TAG, [core])
    except FileNotFoundError:
        return None
    return data


def _validate_all(loaded, schema) -> list:
    """Structurally validate each instance against a preloaded schema. The
    schema is hoisted by the caller so it is meta-validated once, not per file."""
    issues = []
    for path, data, lines in loaded:
        issues.extend(validate(data, schema, file=str(path), lines=lines))
    return issues


def _refuse_if_invalid(cases, rubrics, library) -> None:
    """Validate every loaded instance; raise CorpusInvalid on any E1.7 error."""
    issues = list(detect_duplicates(list(cases)))
    issues += _validate_all(cases, load_schema(_GOLDEN_CASE_TAG))
    if rubrics:
        issues += _validate_all(rubrics, load_schema(_RUBRIC_TAG))
    if library is not None:
        issues += validate(library, load_schema(_METRIC_LIBRARY_TAG),
                           file=_METRIC_LIBRARY_TAG)
    errors = [issue for issue in issues if issue.severity == _ERROR]
    if errors:
        raise CorpusInvalid(issues_to_findings(errors))


def _build_bundle(case_data, rubric_data, library) -> dict:
    """Assemble the canonical symbol bundle ``resolve_rubric`` consumes: rubrics
    keyed by (id, version) plus tags carried by ACTIVE anti_case cases."""
    instances = [(_GOLDEN_CASE_TAG, data) for data in case_data]
    instances += [(_RUBRIC_TAG, data) for data in rubric_data]
    if library is not None:
        instances.append((_METRIC_LIBRARY_TAG, library))
    return build_bundle(instances)
