"""Tests for fe.registry — decorator-based fix registry."""

import sys
import os
import unittest

# Ensure the fix-engine package root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fe.registry import (
    _FIX_REGISTRY,
    register_fix,
    get_fix,
    get_fix_meta,
    list_fixable_rules,
)


class TestRegistry(unittest.TestCase):
    """Core registry behaviour."""

    def setUp(self):
        # Snapshot and clear the global registry before each test.
        self._saved = dict(_FIX_REGISTRY)
        _FIX_REGISTRY.clear()

    def tearDown(self):
        # Restore the registry after each test.
        _FIX_REGISTRY.clear()
        _FIX_REGISTRY.update(self._saved)

    # ------------------------------------------------------------------ #
    # 1. register + lookup
    # ------------------------------------------------------------------ #
    def test_register_and_lookup(self):
        @register_fix("QG-001")
        def fix_qg001(finding, root):
            return "patched"

        fn = get_fix("QG-001")
        self.assertIs(fn, fix_qg001)
        self.assertEqual(fn(None, None), "patched")

    # ------------------------------------------------------------------ #
    # 2. missing rule → None
    # ------------------------------------------------------------------ #
    def test_missing_rule_returns_none(self):
        self.assertIsNone(get_fix("NO-SUCH-RULE"))

    # ------------------------------------------------------------------ #
    # 3. list_fixable_rules returns sorted ids
    # ------------------------------------------------------------------ #
    def test_list_fixable_rules(self):
        @register_fix("ZZ-999")
        def fix_zz(f, r):
            pass

        @register_fix("AA-001")
        def fix_aa(f, r):
            pass

        @register_fix("MM-500")
        def fix_mm(f, r):
            pass

        self.assertEqual(list_fixable_rules(), ["AA-001", "MM-500", "ZZ-999"])

    # ------------------------------------------------------------------ #
    # 4. get_fix_meta returns decorator metadata
    # ------------------------------------------------------------------ #
    def test_get_fix_meta(self):
        @register_fix("QG-META", confidence=0.8, category="review")
        def fix_meta(f, r):
            pass

        meta = get_fix_meta("QG-META")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["rule_id"], "QG-META")
        self.assertAlmostEqual(meta["confidence"], 0.8)
        self.assertEqual(meta["category"], "review")

    def test_get_fix_meta_missing(self):
        self.assertIsNone(get_fix_meta("DOES-NOT-EXIST"))

    # ------------------------------------------------------------------ #
    # 5. decorator preserves the original function identity
    # ------------------------------------------------------------------ #
    def test_decorator_preserves_function(self):
        @register_fix("QG-PRES")
        def my_fixer(finding, root):
            """Docstring kept."""
            return 42

        # The decorator should return the same function object.
        self.assertEqual(my_fixer(None, None), 42)
        self.assertEqual(my_fixer.__doc__, "Docstring kept.")
        self.assertEqual(my_fixer.__name__, "my_fixer")

    # ------------------------------------------------------------------ #
    # 6. default confidence and category
    # ------------------------------------------------------------------ #
    def test_default_meta_values(self):
        @register_fix("QG-DEF")
        def fix_def(f, r):
            pass

        meta = get_fix_meta("QG-DEF")
        self.assertAlmostEqual(meta["confidence"], 0.95)
        self.assertEqual(meta["category"], "safe")


if __name__ == "__main__":
    unittest.main()
