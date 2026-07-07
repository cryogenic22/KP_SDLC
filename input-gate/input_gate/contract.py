"""The def-of-ready contract loader, E1.7-dogfooded.

``load_validated_dor`` resolves the singleton ``sdlc/def-of-ready@1`` instance
from an overlay dir and validates it through ``sdlc_schemas`` before G1 will run
a single check: a missing instance fails closed via ``resolve_instance``
(FileNotFoundError) and a structurally invalid one raises ``ContractInvalid`` --
G1 never preflights against a contract E1.7 would reject, mirroring G4's
``ContractInvalid`` and G5's ``CorpusInvalid``.

``select_kind`` fails closed on an unknown ``--kind`` (``KindNotFound``): a
preflight for a kind absent from the contract must NEVER pass by checking
nothing, so the unknown kind is a loud config error, never a vacuous green.
"""

from __future__ import annotations

from pathlib import Path

from sdlc_schemas import (
    issues_to_findings,
    load_schema,
    resolve_instance,
    validate,
)

_DEF_OF_READY_TAG = "sdlc/def-of-ready@1"
_ERROR = "error"


class ContractInvalid(Exception):
    """The def-of-ready contract is structurally invalid; G1 refuses to run."""

    def __init__(self, path, findings) -> None:
        self.path = path
        self.findings = list(findings)
        super().__init__(
            f"def-of-ready at {path} is invalid ({len(self.findings)} issue(s)); "
            "G1 refuses to preflight against an unvalidated contract"
        )


class KindNotFound(Exception):
    """The requested ``--kind`` is absent from the contract (fail closed)."""

    def __init__(self, kind: str, available) -> None:
        self.kind = kind
        self.available = list(available)
        super().__init__(
            f"kind {kind!r} is not defined in the def-of-ready contract; "
            f"known kinds: {self.available or '(none)'} -- an unknown kind "
            "must never preflight-green by checking nothing"
        )


def load_validated_dor(core_dir):
    """Resolve and E1.7-validate the def-of-ready under an overlay dir.

    Fails closed: a missing instance raises ``FileNotFoundError`` via
    ``resolve_instance`` and a structurally invalid one raises
    ``ContractInvalid`` -- G1 never runs on a contract E1.7 would reject."""
    data, path = resolve_instance(_DEF_OF_READY_TAG, [Path(core_dir)])
    schema = load_schema(_DEF_OF_READY_TAG)
    issues = validate(data, schema, file=str(path))
    errors = [issue for issue in issues if issue.severity == _ERROR]
    if errors:
        raise ContractInvalid(path, issues_to_findings(errors))
    return data, path


def select_kind(contract: dict, kind_name: str) -> dict:
    """Return the requested kind's checklist, fail-closed on the unknown."""
    kinds = contract.get("kinds", {})
    if kind_name not in kinds:
        raise KindNotFound(kind_name, sorted(kinds))
    return kinds[kind_name]
