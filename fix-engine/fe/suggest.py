"""GitHub / GitLab PR suggestion-block generator.

Converts FixPatches into SuggestionBlocks and formats them as
Markdown PR comments with inline ``suggestion`` fenced blocks.
"""

from __future__ import annotations

from typing import List

from fe.types import FixPatch, SuggestionBlock


# Categories that are eligible for PR suggestions.
_SUGGESTABLE_CATEGORIES = frozenset({"safe", "review"})


def generate_suggestions(
    patches: list[FixPatch],
    format: str = "github",
) -> list[SuggestionBlock]:
    """Convert *patches* to PR suggestion blocks.

    Only patches whose category is ``safe`` or ``review`` are turned into
    suggestions (``manual`` patches are excluded).

    Parameters
    ----------
    patches:
        The list of :class:`FixPatch` objects produced by the fix engine.
    format:
        ``"github"`` (default) or ``"gitlab"``.  Both platforms use the
        same ``suggestion`` fence syntax today.

    Returns
    -------
    list[SuggestionBlock]
    """
    suggestions: list[SuggestionBlock] = []
    for patch in patches:
        if patch.category not in _SUGGESTABLE_CATEGORIES:
            continue
        suggestions.append(
            SuggestionBlock(
                rule_id=patch.rule_id,
                file_path=patch.file_path,
                line=patch.line,
                original=patch.original,
                replacement=patch.replacement,
                explanation=patch.explanation,
                confidence=patch.confidence,
                category=patch.category,
            )
        )
    return suggestions


def format_suggestion_comment(
    suggestions: list[SuggestionBlock],
    format: str = "github",
) -> str:
    """Format all *suggestions* as a single PR comment body.

    Parameters
    ----------
    suggestions:
        Pre-built suggestion blocks (usually from :func:`generate_suggestions`).
    format:
        ``"github"`` (default) or ``"gitlab"``.

    Returns
    -------
    str
        A Markdown string ready to be posted as a PR review comment.
    """
    if not suggestions:
        return ""

    parts: list[str] = []
    for suggestion in suggestions:
        if format == "gitlab":
            parts.append(suggestion.to_gitlab_markdown())
        else:
            parts.append(suggestion.to_github_markdown())

    return "\n\n---\n\n".join(parts)
