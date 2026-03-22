"""Tests for fe.config — 3-layer configuration loading."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the fix-engine package root is on sys.path so ``fe`` is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fe.config import load_config, _DEFAULTS


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config."""

    def test_default_config_loads(self):
        """Calling with no arguments returns the built-in defaults."""
        cfg = load_config()
        self.assertIn("fix_engine", cfg)
        fe = cfg["fix_engine"]
        self.assertTrue(fe["enabled"])
        self.assertEqual(fe["auto_apply_threshold"], 0.95)
        self.assertIn("safe", fe["categories"])
        self.assertIn("sarif", fe)

    def test_file_config_overrides_defaults(self):
        """A config file overrides specific default values."""
        override = {
            "fix_engine": {
                "auto_apply_threshold": 0.80,
                "enabled": False,
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(override, tmp)
            tmp_path = tmp.name

        try:
            cfg = load_config(config_path=Path(tmp_path))
            fe = cfg["fix_engine"]
            # Overridden values
            self.assertEqual(fe["auto_apply_threshold"], 0.80)
            self.assertFalse(fe["enabled"])
            # Defaults that were NOT overridden must survive
            self.assertIn("safe", fe["categories"])
            self.assertIn("sarif", fe)
            self.assertEqual(fe["sarif"]["tool_name"], "KP_SDLC Quality Gate")
        finally:
            os.unlink(tmp_path)

    def test_cli_overrides_file(self):
        """CLI overrides beat file-level settings (dotted keys supported)."""
        file_override = {
            "fix_engine": {
                "auto_apply_threshold": 0.80,
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(file_override, tmp)
            tmp_path = tmp.name

        try:
            cfg = load_config(
                config_path=Path(tmp_path),
                cli_overrides={
                    "fix_engine.auto_apply_threshold": 0.50,
                    "fix_engine.enabled": False,
                },
            )
            fe = cfg["fix_engine"]
            # CLI wins
            self.assertEqual(fe["auto_apply_threshold"], 0.50)
            self.assertFalse(fe["enabled"])
        finally:
            os.unlink(tmp_path)

    def test_disabled_fixes_respected(self):
        """disabled_fixes can be set via file config."""
        override = {
            "fix_engine": {
                "disabled_fixes": ["bare_except", "unused_import"],
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(override, tmp)
            tmp_path = tmp.name

        try:
            cfg = load_config(config_path=Path(tmp_path))
            disabled = cfg["fix_engine"]["disabled_fixes"]
            self.assertEqual(disabled, ["bare_except", "unused_import"])
        finally:
            os.unlink(tmp_path)

    def test_confidence_threshold_from_config(self):
        """auto_apply_threshold value flows through correctly."""
        cfg = load_config(
            cli_overrides={"fix_engine.auto_apply_threshold": 0.99}
        )
        self.assertEqual(cfg["fix_engine"]["auto_apply_threshold"], 0.99)

    def test_nonexistent_file_falls_back_to_defaults(self):
        """A missing config file is silently ignored; defaults are used."""
        cfg = load_config(config_path=Path("/tmp/does_not_exist_12345.json"))
        self.assertEqual(cfg, _DEFAULTS)

    def test_deep_merge_preserves_nested_keys(self):
        """Merging a partial categories override keeps unmentioned siblings."""
        override = {
            "fix_engine": {
                "categories": {
                    "safe": {"auto_apply": False},
                }
            }
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as tmp:
            json.dump(override, tmp)
            tmp_path = tmp.name

        try:
            cfg = load_config(config_path=Path(tmp_path))
            cats = cfg["fix_engine"]["categories"]
            # Overridden
            self.assertFalse(cats["safe"]["auto_apply"])
            # Untouched siblings still present
            self.assertIn("review", cats)
            self.assertIn("manual", cats)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
