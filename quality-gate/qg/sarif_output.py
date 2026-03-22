"""SARIF 2.1.0 output module for Quality Gate and Cathedral Keeper.

Converts QG issues and CK findings into SARIF format suitable for
GitHub Code Scanning, GitLab SAST, and other SARIF consumers.

Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

from typing import Any, Dict, List

SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/"
    "master/Schemata/sarif-schema-2.1.0.json"
)

_SEVERITY_MAP = {
    "critical": "error",
    "error": "error",
    "warning": "warning",
    "info": "note",
    "low": "note",
    "medium": "warning",
    "high": "error",
}


def _normalize_path(path: str) -> str:
    """Ensure file path is a relative URI with forward slashes."""
    path = path.replace("\\", "/")
    # Strip leading slash or drive letter (e.g. C:/)
    if len(path) >= 2 and path[1] == ":":
        path = path[2:].lstrip("/")
    path = path.lstrip("/")
    return path


def _map_level(severity: str) -> str:
    """Map a tool severity string to a SARIF level."""
    return _SEVERITY_MAP.get(severity.lower(), "warning")


def _make_sarif_shell(tool_name: str, tool_version: str) -> Dict[str, Any]:
    """Return a minimal valid SARIF 2.1.0 envelope."""
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": tool_name,
                        "version": tool_version,
                        "rules": [],
                    }
                },
                "results": [],
            }
        ],
    }


# ── Public API ────────────────────────────────────────────────────────


def qg_to_sarif(
    issues: List[Dict[str, Any]],
    tool_name: str = "quality-gate",
    tool_version: str = "0.0.0",
) -> Dict[str, Any]:
    """Convert Quality Gate issues to a SARIF 2.1.0 dict.

    Each issue is expected to have:
        file, line, rule, severity, message, suggestion
    """
    sarif = _make_sarif_shell(tool_name, tool_version)
    run = sarif["runs"][0]

    seen_rules: Dict[str, Dict[str, Any]] = {}

    for issue in issues:
        rule_id = issue.get("rule", "unknown")
        if rule_id not in seen_rules:
            rule_def: Dict[str, Any] = {"id": rule_id}
            if issue.get("message"):
                rule_def["shortDescription"] = {"text": issue["message"]}
            if issue.get("suggestion"):
                rule_def["helpUri"] = ""
                rule_def["help"] = {"text": issue["suggestion"]}
            seen_rules[rule_id] = rule_def

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": _map_level(issue.get("severity", "warning")),
            "message": {"text": issue.get("message", "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": _normalize_path(issue.get("file", "")),
                        },
                        "region": {
                            "startLine": issue.get("line", 1),
                        },
                    }
                }
            ],
        }
        run["results"].append(result)

    run["tool"]["driver"]["rules"] = list(seen_rules.values())
    return sarif


def ck_to_sarif(
    findings: List[Dict[str, Any]],
    tool_name: str = "cathedral-keeper",
    tool_version: str = "0.0.0",
) -> Dict[str, Any]:
    """Convert Cathedral Keeper findings to a SARIF 2.1.0 dict.

    Each finding is expected to have:
        policy_id, title, severity, why_it_matters, evidence (list)
    """
    sarif = _make_sarif_shell(tool_name, tool_version)
    run = sarif["runs"][0]

    seen_rules: Dict[str, Dict[str, Any]] = {}

    for finding in findings:
        rule_id = finding.get("policy_id", "unknown")
        if rule_id not in seen_rules:
            rule_def = {
                "id": rule_id,
                "shortDescription": {"text": finding.get("title", "")},
            }
            seen_rules[rule_id] = rule_def

        # Use first evidence entry for location if available
        evidence_list = finding.get("evidence", [])
        if evidence_list:
            ev = evidence_list[0]
            location = {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": _normalize_path(ev.get("file", "")),
                    },
                    "region": {
                        "startLine": ev.get("line", 1),
                    },
                }
            }
            locations = [location]
        else:
            locations = []

        result: Dict[str, Any] = {
            "ruleId": rule_id,
            "level": _map_level(finding.get("severity", "warning")),
            "message": {"text": finding.get("why_it_matters", "")},
            "locations": locations,
        }
        run["results"].append(result)

    run["tool"]["driver"]["rules"] = list(seen_rules.values())
    return sarif


def validate_sarif_schema(sarif: Dict[str, Any]) -> bool:
    """Basic structural validation of a SARIF 2.1.0 dict.

    Checks for required top-level keys, run structure, and result shape.
    Returns True if the structure is valid, False otherwise.
    """
    try:
        if sarif.get("version") != "2.1.0":
            return False
        if "$schema" not in sarif:
            return False

        runs = sarif.get("runs")
        if not isinstance(runs, list) or len(runs) == 0:
            return False

        for run in runs:
            tool = run.get("tool")
            if not isinstance(tool, dict):
                return False
            driver = tool.get("driver")
            if not isinstance(driver, dict):
                return False
            if "name" not in driver:
                return False

            results = run.get("results")
            if not isinstance(results, list):
                return False

            for result in results:
                if "ruleId" not in result:
                    return False
                if "message" not in result or "text" not in result["message"]:
                    return False
                if "level" not in result:
                    return False

        return True
    except Exception:
        return False
