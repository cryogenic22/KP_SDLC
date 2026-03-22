"""Golden tests for every registered fix function.

Each test feeds a known input snippet + finding dict to a fixer and asserts
that the returned FixPatch has the correct replacement, confidence, category,
and a meaningful explanation.

Run with:  python -m pytest tests/test_fix_golden.py -v
   or:     python tests/test_fix_golden.py
"""

from __future__ import annotations

import sys
import os
import unittest

# Ensure the fix-engine package is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import all fix modules so decorators fire and register fixes
import fe.fixes_foundation  # noqa: F401
import fe.fixes_python       # noqa: F401
import fe.fixes_security     # noqa: F401
import fe.fixes_ai_llm       # noqa: F401

from fe.registry import get_fix


# ============================================================================
# Foundation fixes
# ============================================================================

class TestBareExcept(unittest.TestCase):
    def test_golden_bare_except(self):
        input_code = "try:\n    risky()\nexcept:\n    handle()\n"
        finding = {"rule": "bare_except", "file": "test.py", "line": 3}
        patch = get_fix("bare_except")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("except Exception:", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertEqual(patch.confidence, 1.0)
        self.assertGreater(len(patch.explanation), 10)

    def test_no_match(self):
        input_code = "except ValueError:\n    pass\n"
        finding = {"rule": "bare_except", "file": "test.py", "line": 1}
        patch = get_fix("bare_except")(finding, input_code, {})
        self.assertIsNone(patch)


class TestMutableDefault(unittest.TestCase):
    def test_golden_mutable_default(self):
        input_code = "def f(x=[]):\n    return x\n"
        finding = {"rule": "mutable_default", "file": "test.py", "line": 1}
        patch = get_fix("mutable_default")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("x=None", patch.replacement)
        self.assertIn("if x is None:", patch.replacement)
        self.assertIn("x = []", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_dict_default(self):
        input_code = "def g(data={}):\n    pass\n"
        finding = {"rule": "mutable_default", "file": "test.py", "line": 1}
        patch = get_fix("mutable_default")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("data=None", patch.replacement)
        self.assertIn("data = {}", patch.replacement)


class TestNoDebugStatements(unittest.TestCase):
    def test_golden_breakpoint(self):
        input_code = "x = 1\nbreakpoint()\ny = 2\n"
        finding = {"rule": "no_debug_statements", "file": "test.py", "line": 2}
        patch = get_fix("no_debug_statements")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertEqual(patch.replacement, "")
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_golden_debug_print(self):
        input_code = 'x = 1\nprint("DEBUG something")\ny = 2\n'
        finding = {"rule": "no_debug_statements", "file": "test.py", "line": 2}
        patch = get_fix("no_debug_statements")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertEqual(patch.replacement, "")

    def test_normal_print_ignored(self):
        input_code = 'print("hello")\n'
        finding = {"rule": "no_debug_statements", "file": "test.py", "line": 1}
        patch = get_fix("no_debug_statements")(finding, input_code, {})
        self.assertIsNone(patch)


class TestUnusedImport(unittest.TestCase):
    def test_golden_unused_import(self):
        input_code = "import os\nimport sys\nx = 1\n"
        finding = {"rule": "unused_import", "file": "test.py", "line": 1}
        patch = get_fix("unused_import")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertEqual(patch.replacement, "")
        self.assertEqual(patch.category, "safe")
        self.assertEqual(patch.confidence, 1.0)
        self.assertGreater(len(patch.explanation), 10)

    def test_from_import(self):
        input_code = "from os.path import join\n"
        finding = {"rule": "unused_import", "file": "test.py", "line": 1}
        patch = get_fix("unused_import")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertEqual(patch.replacement, "")


class TestTrailingWhitespace(unittest.TestCase):
    def test_golden_trailing_whitespace(self):
        input_code = "x = 1   \ny = 2\n"
        finding = {"rule": "trailing_whitespace", "file": "test.py", "line": 1}
        patch = get_fix("trailing_whitespace")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertEqual(patch.replacement, "x = 1\n")
        self.assertEqual(patch.category, "safe")
        self.assertEqual(patch.confidence, 1.0)
        self.assertGreater(len(patch.explanation), 10)

    def test_no_trailing(self):
        input_code = "x = 1\n"
        finding = {"rule": "trailing_whitespace", "file": "test.py", "line": 1}
        patch = get_fix("trailing_whitespace")(finding, input_code, {})
        self.assertIsNone(patch)


class TestEqualityNone(unittest.TestCase):
    def test_golden_equality_none(self):
        input_code = "if x == None:\n    pass\n"
        finding = {"rule": "equality_none", "file": "test.py", "line": 1}
        patch = get_fix("equality_none")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("is None", patch.replacement)
        self.assertNotIn("==", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertEqual(patch.confidence, 1.0)
        self.assertGreater(len(patch.explanation), 10)

    def test_not_equal_none(self):
        input_code = "if x != None:\n    pass\n"
        finding = {"rule": "equality_none", "file": "test.py", "line": 1}
        patch = get_fix("equality_none")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("is not None", patch.replacement)


class TestEqualityTrueFalse(unittest.TestCase):
    def test_golden_eq_true(self):
        input_code = "if x == True:\n    pass\n"
        finding = {"rule": "equality_true_false", "file": "test.py", "line": 1}
        patch = get_fix("equality_true_false")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("if x:", patch.replacement)
        self.assertNotIn("== True", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_golden_eq_false(self):
        input_code = "if x == False:\n    pass\n"
        finding = {"rule": "equality_true_false", "file": "test.py", "line": 1}
        patch = get_fix("equality_true_false")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("not x", patch.replacement)


class TestEmptyReturn(unittest.TestCase):
    def test_golden_empty_return(self):
        input_code = "def f():\n    return\n"
        finding = {"rule": "empty_return", "file": "test.py", "line": 2}
        patch = get_fix("empty_return")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("return None", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertEqual(patch.confidence, 1.0)
        self.assertGreater(len(patch.explanation), 10)

    def test_return_value_ignored(self):
        input_code = "def f():\n    return 42\n"
        finding = {"rule": "empty_return", "file": "test.py", "line": 2}
        patch = get_fix("empty_return")(finding, input_code, {})
        self.assertIsNone(patch)


# ============================================================================
# Python fixes
# ============================================================================

class TestMissingEncoding(unittest.TestCase):
    def test_golden_missing_encoding(self):
        input_code = "f = open('data.txt')\n"
        finding = {"rule": "missing_encoding", "file": "test.py", "line": 1}
        patch = get_fix("missing_encoding")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("encoding='utf-8'", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_already_has_encoding(self):
        input_code = "f = open('data.txt', encoding='utf-8')\n"
        finding = {"rule": "missing_encoding", "file": "test.py", "line": 1}
        patch = get_fix("missing_encoding")(finding, input_code, {})
        self.assertIsNone(patch)


class TestNoSilentCatch(unittest.TestCase):
    def test_golden_no_silent_catch(self):
        input_code = "try:\n    risky()\nexcept:\n    pass\n"
        finding = {"rule": "no_silent_catch", "file": "test.py", "line": 3}
        patch = get_fix("no_silent_catch")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("except Exception as e:", patch.replacement)
        self.assertIn("logger.warning", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.9)
        self.assertGreater(len(patch.explanation), 10)


class TestRegexCompileInLoop(unittest.TestCase):
    def test_golden_regex_compile_in_loop(self):
        input_code = (
            "for item in items:\n"
            "    pat = re.compile(r'\\d+')\n"
            "    m = pat.match(item)\n"
        )
        finding = {"rule": "regex_compile_in_loop", "file": "test.py", "line": 2}
        patch = get_fix("regex_compile_in_loop")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("pat = re.compile", patch.replacement)
        self.assertIn("for item in items:", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.9)
        self.assertGreater(len(patch.explanation), 10)


class TestStringConcatInLoop(unittest.TestCase):
    def test_golden_string_concat_in_loop(self):
        input_code = (
            "result = ''\n"
            "for c in chars:\n"
            "    result += c\n"
        )
        finding = {"rule": "string_concat_in_loop", "file": "test.py", "line": 3}
        patch = get_fix("string_concat_in_loop")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("append", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.85)
        self.assertGreater(len(patch.explanation), 10)


class TestMissingRequestsTimeout(unittest.TestCase):
    def test_golden_missing_requests_timeout(self):
        input_code = "resp = requests.get('https://api.example.com/data')\n"
        finding = {"rule": "missing_requests_timeout", "file": "test.py", "line": 1}
        patch = get_fix("missing_requests_timeout")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("timeout=30", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_already_has_timeout(self):
        input_code = "resp = requests.get('https://api.example.com', timeout=10)\n"
        finding = {"rule": "missing_requests_timeout", "file": "test.py", "line": 1}
        patch = get_fix("missing_requests_timeout")(finding, input_code, {})
        self.assertIsNone(patch)


class TestReturnInInit(unittest.TestCase):
    def test_golden_return_in_init(self):
        input_code = (
            "class Foo:\n"
            "    def __init__(self):\n"
            "        return 42\n"
        )
        finding = {"rule": "return_in_init", "file": "test.py", "line": 3}
        patch = get_fix("return_in_init")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("return\n", patch.replacement)
        self.assertNotIn("return 42", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)


# ============================================================================
# Security fixes
# ============================================================================

class TestNoTypeEscape(unittest.TestCase):
    def test_golden_no_type_escape(self):
        input_code = "x: int = foo()  # type: ignore\n"
        finding = {"rule": "no_type_escape", "file": "test.py", "line": 1}
        patch = get_fix("no_type_escape")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertNotIn("type: ignore", patch.replacement)
        self.assertIn("x: int = foo()", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.7)
        self.assertGreater(len(patch.explanation), 10)

    def test_with_bracket_spec(self):
        input_code = "x = foo()  # type: ignore[assignment]\n"
        finding = {"rule": "no_type_escape", "file": "test.py", "line": 1}
        patch = get_fix("no_type_escape")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertNotIn("type: ignore", patch.replacement)


class TestCommandInjection(unittest.TestCase):
    def test_golden_command_injection(self):
        input_code = "os.system(cmd)\n"
        finding = {"rule": "command_injection", "file": "test.py", "line": 1}
        patch = get_fix("command_injection")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("subprocess.run", patch.replacement)
        self.assertIn("check=True", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.8)
        self.assertGreater(len(patch.explanation), 10)


class TestAssertInProduction(unittest.TestCase):
    def test_golden_assert_in_production(self):
        input_code = "assert x > 0\n"
        finding = {"rule": "assert_in_production", "file": "test.py", "line": 1}
        patch = get_fix("assert_in_production")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("if not", patch.replacement)
        self.assertIn("raise ValueError", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.85)
        self.assertGreater(len(patch.explanation), 10)

    def test_assert_with_message(self):
        input_code = 'assert x > 0, "x must be positive"\n'
        finding = {"rule": "assert_in_production", "file": "test.py", "line": 1}
        patch = get_fix("assert_in_production")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("raise ValueError", patch.replacement)
        self.assertIn("x must be positive", patch.replacement)


# ============================================================================
# AI / LLM fixes
# ============================================================================

class TestUnboundedTokens(unittest.TestCase):
    def test_golden_unbounded_tokens(self):
        input_code = 'response = client.completions.create(prompt="hello")\n'
        finding = {"rule": "unbounded_tokens", "file": "test.py", "line": 1}
        patch = get_fix("unbounded_tokens")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("max_tokens=4096", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.85)
        self.assertGreater(len(patch.explanation), 10)

    def test_already_has_max_tokens(self):
        input_code = 'response = client.completions.create(prompt="hello", max_tokens=100)\n'
        finding = {"rule": "unbounded_tokens", "file": "test.py", "line": 1}
        patch = get_fix("unbounded_tokens")(finding, input_code, {})
        self.assertIsNone(patch)


class TestLlmTimeout(unittest.TestCase):
    def test_golden_llm_timeout(self):
        input_code = 'response = client.completions.create(prompt="hello")\n'
        finding = {"rule": "llm_timeout", "file": "test.py", "line": 1}
        patch = get_fix("llm_timeout")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("timeout=30", patch.replacement)
        self.assertEqual(patch.category, "review")
        self.assertAlmostEqual(patch.confidence, 0.85)
        self.assertGreater(len(patch.explanation), 10)


class TestMissingAwait(unittest.TestCase):
    def test_golden_missing_await(self):
        input_code = "    result = fetch_data()\n"
        finding = {"rule": "missing_await", "file": "test.py", "line": 1}
        patch = get_fix("missing_await")(finding, input_code, {})
        self.assertIsNotNone(patch)
        self.assertIn("await fetch_data()", patch.replacement)
        self.assertEqual(patch.category, "safe")
        self.assertAlmostEqual(patch.confidence, 0.95)
        self.assertGreater(len(patch.explanation), 10)

    def test_already_has_await(self):
        input_code = "    result = await fetch_data()\n"
        finding = {"rule": "missing_await", "file": "test.py", "line": 1}
        patch = get_fix("missing_await")(finding, input_code, {})
        self.assertIsNone(patch)


if __name__ == "__main__":
    unittest.main()
