"""Enhanced SARIF 2.1.0 formatter for the Fix Engine.

Goes beyond the basic quality-gate SARIF output by adding:
  - fixes[] with artifactChanges and replacements when FixPatches exist
  - codeFlows for CK cycle findings (import chain thread flows)
  - relatedLocations for blast-radius / high fan-in findings
  - invocations[] with execution status and timing
  - Two runs (QG run[0], CK run[1]) when both reports are provided
  - informationUri on each tool driver

Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

from fe.types import FixPatch

# ── Constants ────────────────────────────────────────────────────────

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "master/Schemata/sarif-schema-2.1.0.json"
)

GITHUB_REPO_URL = "https://github.com/anthropics/kp-sdlc"

_SEVERITY_MAP: Dict[str, str] = {
    "critical": "error",
    "error": "error",
    "warning": "warning",
    "info": "note",
    "low": "note",
    "medium": "warning",
    "high": "error",
}

_SARIF_LEVEL_TO_RANK: Dict[str, float] = {
    "error": 9.0,
    "warning": 5.0,
    "note": 1.0,
    "none": 0.0,
}


# ── Helpers ──────────────────────────────────────────────────────────

def _normalize_path(path: str) -> str:
    """Ensure file path is a relative URI with forward slashes."""
    path = path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        path = path[2:].lstrip("/")
    path = path.lstrip("/")
    return path


def _map_level(severity: str) -> str:
    """Map a tool severity string to a SARIF level."""
    return _SEVERITY_MAP.get(severity.lower(), "warning")


def _build_invocation(*, success: bool = True, start: str | None = None,
                      end: str | None = None) -> Dict[str, Any]:
    """Build a SARIF invocation object."""
    inv: Dict[str, Any] = {
        "executionSuccessful": success,
    }
    if start:
        inv["startTimeUtc"] = start
    if end:
        inv["endTimeUtc"] = end
    return inv


def _build_fix_from_patch(patch: FixPatch) -> Dict[str, Any]:
    """Build a SARIF `fix` object from a FixPatch."""
    return {
        "description": {
            "text": patch.explanation,
        },
        "artifactChanges": [
            {
                "artifactLocation": {
                    "uri": _normalize_path(patch.file_path),
                },
                "replacements": [
                    {
                        "deletedRegion": {
                            "startLine": patch.line,
                        },
                        "insertedContent": {
                            "text": patch.replacement,
                        },
                    }
                ],
            }
        ],
    }


def _build_code_flows(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build codeFlows from cycle evidence (import chain)."""
    if not evidence or len(evidence) < 2:
        return []

    thread_flow_locations = []
    for idx, ev in enumerate(evidence):
        loc: Dict[str, Any] = {
            "location": {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": _normalize_path(ev.get("file", "")),
                    },
                    "region": {
                        "startLine": ev.get("line", 1),
                    },
                },
                "message": {
                    "text": ev.get("note", ev.get("snippet", "")),
                },
            },
        }
        thread_flow_locations.append(loc)

    return [
        {
            "threadFlows": [
                {
                    "locations": thread_flow_locations,
                }
            ],
        }
    ]


def _build_related_locations(evidence: List[Dict[str, Any]],
                             metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build relatedLocations for blast-radius / fan-in findings."""
    related: List[Dict[str, Any]] = []
    for idx, ev in enumerate(evidence):
        entry: Dict[str, Any] = {
            "id": idx,
            "physicalLocation": {
                "artifactLocation": {
                    "uri": _normalize_path(ev.get("file", "")),
                },
                "region": {
                    "startLine": ev.get("line", 1),
                },
            },
            "message": {
                "text": ev.get("note", ev.get("snippet", "")),
            },
        }
        related.append(entry)

    # Add fan-in info as a synthetic related location
    fan_in = metadata.get("fan_in")
    if fan_in is not None and evidence:
        related.append({
            "id": len(evidence),
            "message": {
                "text": f"fan_in={fan_in}",
            },
        })

    return related


# ── Run builders ─────────────────────────────────────────────────────

def _build_qg_run(qg_report: dict,
                   patches: List[FixPatch] | None = None,
                   config: dict | None = None) -> Dict[str, Any]:
    """Build the Quality Gate SARIF run."""
    cfg = config or {}
    tool_version = cfg.get("qg_version", "0.1.0")

    issues = qg_report.get("issues", [])

    # Index patches by (file, line, rule) for fast lookup
    patch_index: Dict[tuple, FixPatch] = {}
    if patches:
        for p in patches:
            key = (_normalize_path(p.file_path), p.line, p.rule_id)
            patch_index[key] = p

    seen_rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    for issue in issues:
        rule_id = issue.get("rule", "unknown")
        if rule_id not in seen_rules:
            rule_def: Dict[str, Any] = {"id": rule_id}
            if issue.get("message"):
                rule_def["shortDescription"] = {"text": issue["message"]}
            if issue.get("suggestion"):
                rule_def["help"] = {"text": issue["suggestion"]}
            seen_rules[rule_id] = rule_def

        file_uri = _normalize_path(issue.get("file", ""))
        line = issue.get("line", 1)
        level = _map_level(issue.get("severity", "warning"))

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": issue.get("message", "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_uri},
                        "region": {"startLine": line},
                    }
                }
            ],
        }

        # Attach fix if a matching patch exists
        patch_key = (file_uri, line, rule_id)
        patch = patch_index.get(patch_key)
        if patch is not None:
            result["fixes"] = [_build_fix_from_patch(patch)]

        results.append(result)

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    run: Dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "quality-gate",
                "version": tool_version,
                "informationUri": GITHUB_REPO_URL,
                "rules": list(seen_rules.values()),
            }
        },
        "invocations": [
            _build_invocation(success=True, start=now_utc, end=now_utc),
        ],
        "results": results,
    }
    return run


def _build_ck_run(ck_report: dict,
                  config: dict | None = None) -> Dict[str, Any]:
    """Build the Cathedral Keeper SARIF run."""
    cfg = config or {}
    tool_version = cfg.get("ck_version", "0.1.0")

    findings = ck_report.get("findings", [])

    seen_rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    for finding in findings:
        rule_id = finding.get("policy_id", "unknown")
        if rule_id not in seen_rules:
            rule_def: Dict[str, Any] = {
                "id": rule_id,
                "shortDescription": {"text": finding.get("title", "")},
            }
            seen_rules[rule_id] = rule_def

        evidence = finding.get("evidence", [])
        metadata = finding.get("metadata", {})

        # Primary location from first evidence entry
        if evidence:
            ev = evidence[0]
            locations = [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": _normalize_path(ev.get("file", "")),
                        },
                        "region": {
                            "startLine": ev.get("line", 1),
                        },
                    }
                }
            ]
        else:
            locations = []

        level = _map_level(finding.get("severity", "warning"))
        message_text = finding.get("title", finding.get("why_it_matters", ""))

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": message_text},
            "locations": locations,
        }

        # codeFlows for CYCLE findings
        if "CYCLE" in rule_id.upper():
            code_flows = _build_code_flows(evidence)
            if code_flows:
                result["codeFlows"] = code_flows

        # relatedLocations for blast-radius / fan-in findings
        if metadata.get("fan_in") is not None:
            related = _build_related_locations(evidence, metadata)
            if related:
                result["relatedLocations"] = related

        results.append(result)

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    run: Dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "cathedral-keeper",
                "version": tool_version,
                "informationUri": GITHUB_REPO_URL,
                "rules": list(seen_rules.values()),
            }
        },
        "invocations": [
            _build_invocation(success=True, start=now_utc, end=now_utc),
        ],
        "results": results,
    }
    return run


# ── Public API ───────────────────────────────────────────────────────

def generate_sarif(
    *,
    qg_report: dict,
    ck_report: dict | None = None,
    config: dict | None = None,
    patches: list[FixPatch] | None = None,
) -> dict:
    """Generate an enhanced SARIF 2.1.0 document.

    Parameters
    ----------
    qg_report : dict
        Quality Gate report with ``issues`` list.
    ck_report : dict | None
        Cathedral Keeper report with ``findings`` list.  When provided a
        second run is added to the SARIF output.
    config : dict | None
        Optional config overrides (``qg_version``, ``ck_version``).
    patches : list[FixPatch] | None
        Fix patches to embed as SARIF ``fixes[]`` on matching results.

    Returns
    -------
    dict
        A SARIF 2.1.0 compliant dictionary ready for ``json.dumps()``.
    """
    runs: List[Dict[str, Any]] = []

    # Run 0 — Quality Gate
    runs.append(_build_qg_run(qg_report, patches=patches, config=config))

    # Run 1 — Cathedral Keeper (optional)
    if ck_report is not None:
        runs.append(_build_ck_run(ck_report, config=config))

    sarif: Dict[str, Any] = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": runs,
    }
    return sarif
