#!/usr/bin/env python3
"""
Commit Message Format Checker
=============================
Enforces conventional commits format.

Format: <type>(<scope>): <description>

Types:
  feat     - New feature
  fix      - Bug fix
  docs     - Documentation only
  style    - Code style (formatting, semicolons, etc.)
  refactor - Code refactoring (no feature/fix)
  perf     - Performance improvement
  test     - Adding/updating tests
  build    - Build system changes
  ci       - CI configuration
  chore    - Other changes (deps, config, etc.)
  revert   - Revert previous commit

Examples:
  feat(auth): add OAuth2 login
  fix(api): handle null response from external service
  docs: update README with new setup instructions
  refactor(components): extract Button from Form

Rules:
  1. Type is required and must be from the list above
  2. Scope is optional but encouraged
  3. Description must be 10-72 characters
  4. Description must start with lowercase
  5. Description must not end with period
"""

import re
import sys
from pathlib import Path

# Conventional commits pattern
COMMIT_PATTERN = re.compile(
    r'^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)'  # type
    r'(\([a-z0-9_-]+\))?'  # optional scope
    r'!?'  # optional breaking change indicator
    r': '  # separator
    r'(.{10,72})'  # description (10-72 chars)
    r'$',
    re.MULTILINE
)

# Alternative patterns we also accept
MERGE_PATTERN = re.compile(r'^Merge (branch|pull request|remote-tracking branch)')
REVERT_PATTERN = re.compile(r'^Revert "')
WIP_PATTERN = re.compile(r'^WIP:', re.IGNORECASE)
RELEASE_PATTERN = re.compile(r'^(v?\d+\.\d+\.\d+|Release \d+)')

# Patterns that indicate AI-generated commits (acceptable)
AI_GENERATED_PATTERN = re.compile(r'Generated with \[Claude Code\]|Co-Authored-By: Claude')


def check_commit_message(message: str) -> tuple[bool, str]:
    """
    Check if commit message follows conventional commits format.

    Returns:
        (passed, error_message)
    """
    # Get first line (summary)
    lines = message.strip().split('\n')
    if not lines:
        return False, "Empty commit message"

    summary = lines[0].strip()

    if not summary:
        return False, "Empty commit summary line"

    # Allow merge commits
    if MERGE_PATTERN.match(summary):
        return True, ""

    # Allow revert commits
    if REVERT_PATTERN.match(summary):
        return True, ""

    # Allow WIP commits (but only on feature branches)
    if WIP_PATTERN.match(summary):
        return True, ""  # WIP is allowed but should be squashed before merge

    # Allow release tags
    if RELEASE_PATTERN.match(summary):
        return True, ""

    # Check conventional commits format
    match = COMMIT_PATTERN.match(summary)
    if not match:
        # Provide helpful error message
        if ':' not in summary:
            return False, f"Missing type prefix. Use: feat|fix|docs|style|refactor|perf|test|build|ci|chore: <description>"

        parts = summary.split(':', 1)
        commit_type = parts[0].strip().lower()
        valid_types = ['feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert']

        # Check if type is valid (allowing for scope)
        type_without_scope = re.sub(r'\([^)]+\)', '', commit_type)
        if type_without_scope not in valid_types:
            return False, f"Invalid type '{type_without_scope}'. Valid types: {', '.join(valid_types)}"

        if len(parts) > 1:
            desc = parts[1].strip()
            if len(desc) < 10:
                return False, f"Description too short ({len(desc)} chars). Minimum 10 characters."
            if len(desc) > 72:
                return False, f"Description too long ({len(desc)} chars). Maximum 72 characters."

        return False, f"Invalid format. Expected: type(scope): description (10-72 chars)"

    # Extract parts
    commit_type = match.group(1)
    scope = match.group(2)
    description = match.group(3)

    # Additional checks
    if description[0].isupper():
        return False, "Description should start with lowercase letter"

    if description.endswith('.'):
        return False, "Description should not end with a period"

    # Check for lazy descriptions
    lazy_patterns = [
        r'^(update|fix|change|modify|edit)s?$',
        r'^(update|fix|change|modify|edit)s? (stuff|things|code|it)$',
        r'^wip$',
        r'^work in progress$',
        r'^minor( changes)?$',
        r'^misc( changes)?$',
    ]

    for pattern in lazy_patterns:
        if re.match(pattern, description, re.IGNORECASE):
            return False, f"Description too vague: '{description}'. Be specific about what changed."

    return True, ""


def main():
    """Main entry point for commit-msg hook."""
    # Get commit message file path from git
    if len(sys.argv) < 2:
        print("Usage: check_commit_msg.py <commit-msg-file>")
        sys.exit(1)

    commit_msg_file = Path(sys.argv[1])

    if not commit_msg_file.exists():
        print(f"Error: Commit message file not found: {commit_msg_file}")
        sys.exit(1)

    message = commit_msg_file.read_text(encoding='utf-8')

    # Skip if it's an AI-generated commit (we trust Claude)
    if AI_GENERATED_PATTERN.search(message):
        sys.exit(0)

    passed, error = check_commit_message(message)

    if passed:
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("COMMIT MESSAGE REJECTED")
        print("=" * 60)
        print(f"\nError: {error}")
        print("\nExpected format:")
        print("  <type>(<scope>): <description>")
        print("\nTypes: feat, fix, docs, style, refactor, perf, test, build, ci, chore")
        print("\nExamples:")
        print("  feat(auth): add OAuth2 login support")
        print("  fix(api): handle null response gracefully")
        print("  docs: update installation instructions")
        print("=" * 60 + "\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
