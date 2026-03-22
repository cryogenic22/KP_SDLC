"""Tests for fe.suggest — PR suggestion-block generation."""

from __future__ import annotations

import sys
import os
import unittest

# Ensure the fix-engine package root is on sys.path so ``fe`` is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fe.types import FixPatch, SuggestionBlock
from fe.suggest import generate_suggestions, format_suggestion_comment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_patch(
    rule_id: str = "bare_except",
    file_path: str = "src/handler.py",
    line: int = 42,
    original: str = "except:",
    replacement: str = "except Exception:",
    explanation: str = "Bare except catches SystemExit and KeyboardInterrupt.",
    confidence: float = 1.0,
    category: str = "safe",
) -> FixPatch:
    return FixPatch(
        rule_id=rule_id,
        file_path=file_path,
        line=line,
        original=original,
        replacement=replacement,
        explanation=explanation,
        confidence=confidence,
        category=category,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGenerateSuggestions(unittest.TestCase):
    """Tests for generate_suggestions."""

    def test_generate_suggestions_from_patches(self):
        """Safe and review patches produce SuggestionBlocks."""
        patches = [
            _make_patch(category="safe"),
            _make_patch(rule_id="unused_import", category="review", line=10),
        ]
        suggestions = generate_suggestions(patches)
        self.assertEqual(len(suggestions), 2)
        self.assertIsInstance(suggestions[0], SuggestionBlock)
        self.assertIsInstance(suggestions[1], SuggestionBlock)

    def test_github_suggestion_format(self):
        """GitHub markdown contains the ```suggestion fence."""
        patch = _make_patch()
        suggestions = generate_suggestions([patch], format="github")
        md = suggestions[0].to_github_markdown()
        self.assertIn("```suggestion", md)
        self.assertIn("except Exception:", md)
        self.assertIn("bare_except", md)
        self.assertIn("src/handler.py:42", md)

    def test_gitlab_suggestion_format(self):
        """GitLab markdown also uses the suggestion fence."""
        patch = _make_patch()
        suggestions = generate_suggestions([patch], format="gitlab")
        md = suggestions[0].to_gitlab_markdown()
        self.assertIn("```suggestion", md)
        self.assertIn("except Exception:", md)

    def test_empty_patches_empty_suggestions(self):
        """An empty patch list yields an empty suggestion list."""
        suggestions = generate_suggestions([])
        self.assertEqual(suggestions, [])

    def test_suggestion_includes_explanation(self):
        """Each suggestion block contains the human-readable explanation."""
        patch = _make_patch(explanation="Use specific exception types.")
        suggestions = generate_suggestions([patch])
        md = suggestions[0].to_github_markdown()
        self.assertIn("Use specific exception types.", md)

    def test_suggestion_includes_confidence(self):
        """Confidence score appears in the rendered markdown."""
        patch = _make_patch(confidence=0.87)
        suggestions = generate_suggestions([patch])
        md = suggestions[0].to_github_markdown()
        self.assertIn("0.87", md)

    def test_format_comment_body_multiple_suggestions(self):
        """Multiple suggestions are joined with horizontal rules."""
        patches = [
            _make_patch(line=10),
            _make_patch(rule_id="unused_import", line=20, category="review"),
        ]
        suggestions = generate_suggestions(patches)
        body = format_suggestion_comment(suggestions)
        # Two suggestion blocks separated by a horizontal rule
        self.assertIn("---", body)
        self.assertEqual(body.count("```suggestion"), 2)

    def test_only_review_and_safe_categories_get_suggestions(self):
        """Manual-category patches are excluded from suggestions."""
        patches = [
            _make_patch(category="safe"),
            _make_patch(category="review", line=20),
            _make_patch(category="manual", line=30),
        ]
        suggestions = generate_suggestions(patches)
        self.assertEqual(len(suggestions), 2)
        categories = {s.category for s in suggestions}
        self.assertNotIn("manual", categories)

    def test_format_comment_empty_suggestions(self):
        """An empty suggestion list yields an empty comment body."""
        body = format_suggestion_comment([])
        self.assertEqual(body, "")

    def test_suggestion_preserves_patch_fields(self):
        """All key fields from the FixPatch are carried over."""
        patch = _make_patch(
            rule_id="no_print",
            file_path="lib/utils.py",
            line=99,
            replacement="logging.info(msg)",
            confidence=0.72,
            category="review",
        )
        suggestions = generate_suggestions([patch])
        s = suggestions[0]
        self.assertEqual(s.rule_id, "no_print")
        self.assertEqual(s.file_path, "lib/utils.py")
        self.assertEqual(s.line, 99)
        self.assertEqual(s.replacement, "logging.info(msg)")
        self.assertEqual(s.confidence, 0.72)
        self.assertEqual(s.category, "review")


if __name__ == "__main__":
    unittest.main()
