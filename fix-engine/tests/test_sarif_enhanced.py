"""Tests for the enhanced SARIF 2.1.0 formatter.

Run:
    cd fix-engine && python tests/test_sarif_enhanced.py
"""

from __future__ import annotations

import json
import sys
import os
import unittest

# Ensure the fix-engine root is on sys.path so imports resolve.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fe.types import FixPatch
from sarif_formatter import generate_sarif, GITHUB_REPO_URL

# ── Fixtures ─────────────────────────────────────────────────────────

SAMPLE_QG: dict = {
    "stats": {"files_checked": 10},
    "issues": [
        {
            "file": "app.py",
            "line": 10,
            "rule": "bare_except",
            "severity": "warning",
            "message": "Bare except",
            "suggestion": "Use except Exception:",
        },
    ],
}

SAMPLE_CK: dict = {
    "findings": [
        {
            "policy_id": "CK-ARCH-CYCLES",
            "title": "Import cycle: a\u2192b\u2192a",
            "severity": "medium",
            "evidence": [
                {"file": "a.py", "line": 1, "snippet": "import b", "note": "cycle start"},
                {"file": "b.py", "line": 3, "snippet": "import a", "note": "cycle end"},
            ],
            "metadata": {},
        },
        {
            "policy_id": "CK-BLAST-RADIUS",
            "title": "High fan-in",
            "severity": "medium",
            "evidence": [
                {"file": "models.py", "line": 1, "snippet": "fan-in=16", "note": "hotspot"},
            ],
            "metadata": {"fan_in": 16},
        },
    ],
}

SAMPLE_PATCH = FixPatch(
    rule_id="bare_except",
    file_path="app.py",
    line=10,
    original="except:",
    replacement="except Exception:",
    explanation="Bare except catches SystemExit and KeyboardInterrupt",
    confidence=0.95,
    category="safe",
)


# ── Tests ────────────────────────────────────────────────────────────

class TestSarifEnhanced(unittest.TestCase):
    """12+ tests for the enhanced SARIF formatter."""

    # ---- run structure ---------------------------------------------------

    def test_sarif_has_two_runs_when_ck_provided(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK)
        self.assertEqual(len(sarif["runs"]), 2)
        self.assertEqual(sarif["runs"][0]["tool"]["driver"]["name"], "quality-gate")
        self.assertEqual(sarif["runs"][1]["tool"]["driver"]["name"], "cathedral-keeper")

    def test_sarif_has_one_run_when_ck_missing(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG)
        self.assertEqual(len(sarif["runs"]), 1)
        self.assertEqual(sarif["runs"][0]["tool"]["driver"]["name"], "quality-gate")

    # ---- fixes -----------------------------------------------------------

    def test_sarif_fixes_array_present_when_patch_exists(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, patches=[SAMPLE_PATCH])
        result = sarif["runs"][0]["results"][0]
        self.assertIn("fixes", result)
        self.assertIsInstance(result["fixes"], list)
        self.assertGreater(len(result["fixes"]), 0)

    def test_sarif_fixes_array_has_replacement(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, patches=[SAMPLE_PATCH])
        fix = sarif["runs"][0]["results"][0]["fixes"][0]
        # fix must have artifactChanges with at least one replacement
        self.assertIn("artifactChanges", fix)
        changes = fix["artifactChanges"]
        self.assertGreater(len(changes), 0)
        replacement = changes[0]["replacements"][0]
        self.assertIn("deletedRegion", replacement)
        self.assertIn("insertedContent", replacement)
        self.assertEqual(replacement["insertedContent"]["text"], "except Exception:")

    # ---- codeFlows -------------------------------------------------------

    def test_sarif_code_flows_for_cycle_findings(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK)
        ck_run = sarif["runs"][1]
        # The first CK finding is CYCLES — it must have codeFlows
        cycle_result = ck_run["results"][0]
        self.assertIn("codeFlows", cycle_result)
        flows = cycle_result["codeFlows"]
        self.assertGreater(len(flows), 0)
        thread_flows = flows[0]["threadFlows"]
        self.assertGreater(len(thread_flows), 0)
        locations = thread_flows[0]["locations"]
        self.assertEqual(len(locations), 2)
        # Verify the two files in the thread flow
        uris = [
            loc["location"]["physicalLocation"]["artifactLocation"]["uri"]
            for loc in locations
        ]
        self.assertEqual(uris, ["a.py", "b.py"])

    # ---- relatedLocations ------------------------------------------------

    def test_sarif_related_locations_for_blast_radius(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK)
        ck_run = sarif["runs"][1]
        # The second CK finding is BLAST-RADIUS — must have relatedLocations
        blast_result = ck_run["results"][1]
        self.assertIn("relatedLocations", blast_result)
        related = blast_result["relatedLocations"]
        self.assertGreater(len(related), 0)
        # Should include a fan_in annotation
        fan_in_msgs = [r["message"]["text"] for r in related if "fan_in" in r.get("message", {}).get("text", "")]
        self.assertTrue(len(fan_in_msgs) > 0, "Expected a relatedLocation with fan_in info")

    # ---- invocations -----------------------------------------------------

    def test_sarif_invocations_present(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK)
        for run in sarif["runs"]:
            self.assertIn("invocations", run)
            self.assertIsInstance(run["invocations"], list)
            self.assertGreater(len(run["invocations"]), 0)
            inv = run["invocations"][0]
            self.assertIn("executionSuccessful", inv)
            self.assertTrue(inv["executionSuccessful"])

    # ---- severity mapping ------------------------------------------------

    def test_sarif_severity_mapping(self):
        """Verify that high->error, medium->warning, low->note."""
        ck_data: dict = {
            "findings": [
                {
                    "policy_id": "CK-HIGH",
                    "title": "High sev",
                    "severity": "high",
                    "evidence": [{"file": "x.py", "line": 1, "snippet": "x", "note": "n"}],
                    "metadata": {},
                },
                {
                    "policy_id": "CK-MED",
                    "title": "Med sev",
                    "severity": "medium",
                    "evidence": [{"file": "y.py", "line": 1, "snippet": "y", "note": "n"}],
                    "metadata": {},
                },
                {
                    "policy_id": "CK-LOW",
                    "title": "Low sev",
                    "severity": "low",
                    "evidence": [{"file": "z.py", "line": 1, "snippet": "z", "note": "n"}],
                    "metadata": {},
                },
            ],
        }
        sarif = generate_sarif(qg_report={"stats": {}, "issues": []}, ck_report=ck_data)
        ck_results = sarif["runs"][1]["results"]
        levels = [r["level"] for r in ck_results]
        self.assertEqual(levels, ["error", "warning", "note"])

    # ---- informationUri --------------------------------------------------

    def test_sarif_information_uri(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK)
        for run in sarif["runs"]:
            driver = run["tool"]["driver"]
            self.assertIn("informationUri", driver)
            self.assertEqual(driver["informationUri"], GITHUB_REPO_URL)

    # ---- edge cases ------------------------------------------------------

    def test_sarif_empty_reports(self):
        sarif = generate_sarif(qg_report={"stats": {}, "issues": []})
        self.assertEqual(len(sarif["runs"]), 1)
        self.assertEqual(sarif["runs"][0]["results"], [])

    def test_sarif_json_serializable(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG, ck_report=SAMPLE_CK, patches=[SAMPLE_PATCH])
        # Must not raise
        text = json.dumps(sarif, indent=2)
        self.assertIsInstance(text, str)
        # Round-trip
        loaded = json.loads(text)
        self.assertEqual(loaded["version"], "2.1.0")

    def test_sarif_version_2_1_0(self):
        sarif = generate_sarif(qg_report=SAMPLE_QG)
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertIn("$schema", sarif)
        self.assertIn("sarif-schema-2.1.0", sarif["$schema"])


if __name__ == "__main__":
    unittest.main()
