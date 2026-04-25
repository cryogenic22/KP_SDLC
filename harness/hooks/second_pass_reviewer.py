#!/usr/bin/env python3
"""Second-pass reviewer — fresh-context Claude review of a PR diff against
the design-philosophy Tier 2 checklist.

Zero-dependency by design (stdlib only). Matches KP_SDLC's no-pip-install
philosophy. Posts JSON-encoded HTTP request to api.anthropic.com directly.

Usage (in CI workflow):
    python .harness/hooks/second_pass_reviewer.py \\
        --base "$BASE_SHA" --head "$HEAD_SHA" \\
        --principles .claude/skills/design-philosophy/SKILL.md \\
        > review.md

Required env:
    ANTHROPIC_API_KEY      — required; if absent, exits 0 with skip notice
    LLM_MODEL              — optional; defaults to claude-sonnet-4-6
    SECOND_PASS_MAX_TOKENS — optional; defaults to 4096
    SECOND_PASS_DIFF_LIMIT — optional; defaults to 200000 (200KB)

Exit codes:
    0  success (or graceful skip)
    1  unrecoverable error (network, API, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_DIFF_LIMIT = 200_000


def get_diff(base: str, head: str, limit: int) -> str:
    out = subprocess.check_output(
        ["git", "diff", f"{base}...{head}"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if len(out) > limit:
        return out[:limit] + f"\n\n[diff truncated at {limit:,} characters]"
    return out


def build_prompt(principles: str, diff: str) -> str:
    return f"""You are reviewing a pull request. You have NO prior context on this PR
or codebase — only the design-philosophy below and the git diff.

Walk the 22-flag Tier 2 checklist below. For each flag, mark exactly one:
PASS · N/A · FIXED-NEEDED · JUSTIFIED-IF-EXPLAINED, with a one-line reason
citing specific files/lines from the diff.

End with:
1. A summary line: "X PASS · Y N/A · Z FIXED-NEEDED · W JUSTIFIED-IF-EXPLAINED"
2. Specific actionable items (if any) — what should change before merge?
3. A confidence note — what could you not assess from the diff alone?

Be concrete, not generic. Cite line numbers. If a flag does not apply
because the change has no functions / no APIs / no Python / etc., mark
N/A explicitly with the reason — don't pad PASS for irrelevant flags.

--- design-philosophy (the rules you are reviewing against) ---

{principles}

--- git diff (the only context you have on this PR) ---

{diff}
"""


def call_anthropic(api_key: str, model: str, max_tokens: int, prompt: str) -> str:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Read body for diagnostic; include in error
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"Anthropic API HTTP {e.code}: {err_body}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Network error contacting Anthropic API: {e}") from e

    blocks = data.get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base commit SHA")
    parser.add_argument("--head", required=True, help="head commit SHA")
    parser.add_argument(
        "--principles",
        required=True,
        help="path to design-philosophy SKILL.md",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "[second-pass-reviewer] ANTHROPIC_API_KEY not set — skipping",
            file=sys.stderr,
        )
        return 0

    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    max_tokens = int(os.environ.get("SECOND_PASS_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    diff_limit = int(os.environ.get("SECOND_PASS_DIFF_LIMIT", DEFAULT_DIFF_LIMIT))

    try:
        with open(args.principles, encoding="utf-8") as f:
            principles = f.read()
    except FileNotFoundError:
        print(f"[second-pass-reviewer] principles file not found: {args.principles}", file=sys.stderr)
        return 1

    diff = get_diff(args.base, args.head, diff_limit)
    if not diff.strip():
        print("[second-pass-reviewer] empty diff — nothing to review", file=sys.stderr)
        return 0

    prompt = build_prompt(principles, diff)
    review = call_anthropic(api_key, model, max_tokens, prompt)
    print(review)
    return 0


if __name__ == "__main__":
    sys.exit(main())
