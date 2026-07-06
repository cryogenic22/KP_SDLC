#!/usr/bin/env python3
"""Generate (and verify) .github/workflows/quality.yml from harness/ci/quality.yml.tmpl.

Single-source doctrine: harness/ci/quality.yml.tmpl is the one description of
the quality workflow. Init'd repos consume it via sdlc-init; the engine repo
itself cannot run it verbatim (no uv/ruff/mypy/pytest/Postgres surface), so
this generator assembles the engine's own workflow from the same tmpl:

- name/on/permissions/concurrency: copied from the tmpl;
- ``surface`` job: extracted from the tmpl verbatim (text-slice with
  structural assertions — no YAML lib under the zero-dependency doctrine);
- ``process`` job: the tmpl's process job with the vendor script path
  (.github/scripts/check_pr_template.py) rewired to the engine path
  (harness/process/check_pr_template.py);
- ``mechanical`` job: engine-specific, pinned by ENGINE_PROFILE below;
  its SARIF-upload step is extracted from the tmpl verbatim.

The rendered file is committed; drift fails CI twice over (the workflow's own
first step runs ``--check``, and test_quality_workflow_sync.py enforces the
same equality). This file deliberately lives outside harness/ci/ because
sdlc-init's DIR_MAP fans that whole directory into init'd repos' workflows.

Usage:
  python harness/selfci/gen_quality_workflow.py            # write the workflow
  python harness/selfci/gen_quality_workflow.py --check    # exit 1 on drift (CI)
  python harness/selfci/gen_quality_workflow.py --root R   # explicit repo root

Writes LF-only (CRLF in a .yml breaks POSIX CI). Zero dependencies — stdlib only.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

# ── Engine profile ────────────────────────────────────────────────────
# The engine repo's knobs. Flip points — each is a one-line change here,
# then regenerate and commit the workflow together with this file (the sync
# test makes a half-flip impossible):
#
#   QG_CMD           report-only today: '--mode audit' exits 0 naturally, so
#                    no continue-on-error mask is needed. After E0.6 commits
#                    .quality-gate.baseline.json, flip to '--mode check
#                    --baseline .quality-gate.baseline.json' (blocking ratchet).
#   CK_BLOCKING      False -> True drops the continue-on-error mask. Flip once
#                    E0.4's baseline machinery or E0.6 remediation clears the
#                    >=high findings CK exits 1 on today (236 on 2026-07-06).
#   INCLUDE_PROCESS  already True from birth — E0.3 shipped
#                    harness/process/check_pr_template.py before self-CI landed.
ENGINE_PROFILE = {
    "PYTHON_VERSION": "3.12",
    "QG_STEP_NAME": "Quality Gate (report-only until E0.6 baseline)",
    "QG_CMD": (
        "python quality-gate/quality_gate.py"
        " --root . --mode audit --json --sarif qg.sarif"
    ),
    "CK_BLOCKING": False,
    "INCLUDE_PROCESS": True,
}

_CK_CMD = (
    "python cathedral-keeper/ck.py analyze --root . --blast-radius --verbose"
    " --out-md ck-report.md --out-json ck-report.json"
)

_VENDOR_PR_LINT = "python .github/scripts/check_pr_template.py"
_ENGINE_PR_LINT = "python harness/process/check_pr_template.py"

_HEADER = (
    "# DO NOT EDIT — generated from harness/ci/quality.yml.tmpl by\n"
    "# harness/selfci/gen_quality_workflow.py (ENGINE_PROFILE pins the engine-repo\n"
    "# mechanical job). Edit the tmpl or the profile, then regenerate:\n"
    "#   python harness/selfci/gen_quality_workflow.py\n"
    "# CI fails on drift: this workflow's first mechanical step re-runs the\n"
    "# generator with --check, and harness/selfci/tests/test_quality_workflow_sync.py\n"
    "# enforces the same equality.\n"
    "# Note: the surface job posts a PR comment; fork PRs run with a read-only\n"
    "# token so that step can fail on forks (acceptable for a single-owner repo).\n"
)

_JOB_RE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def _norm(text: str) -> str:
    """CRLF-normalize (Windows checkouts under core.autocrlf)."""
    return text.replace("\r\n", "\n")


def _job_starts(lines: List[str]) -> List[Tuple[int, str]]:
    """Return (line_index, job_name) for every top-level job under ``jobs:``."""
    try:
        jobs_i = lines.index("jobs:")
    except ValueError:
        raise ValueError("tmpl has no top-level 'jobs:' line — cannot slice jobs")
    starts = []
    for i in range(jobs_i + 1, len(lines)):
        m = _JOB_RE.match(lines[i])
        if m:
            starts.append((i, m.group(1)))
    if not starts:
        raise ValueError("tmpl 'jobs:' mapping contains no 2-space-indented jobs")
    return starts


def extract_job(tmpl_text: str, job_name: str) -> str:
    """Text-slice the top-level job ``job_name`` from the tmpl, verbatim.

    Structural assertions guard the slice (a tmpl reformat must fail loudly,
    not mis-slice): the block must start with the 2-space-indented job key.
    """
    lines = _norm(tmpl_text).split("\n")
    starts = _job_starts(lines)
    names = [name for _, name in starts]
    if job_name not in names:
        raise ValueError(f"tmpl has no job '{job_name}' (found: {names})")
    pos = names.index(job_name)
    start = starts[pos][0]
    end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
    block_lines = lines[start:end]
    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
    block = "\n".join(block_lines)
    if not block.startswith(f"  {job_name}:"):
        raise ValueError(f"sliced block for '{job_name}' does not start with its key")
    return block


def extract_preamble(tmpl_text: str) -> str:
    """Copy name/on/permissions/concurrency from the tmpl (comments excluded)."""
    lines = _norm(tmpl_text).split("\n")
    name_i = next((i for i, ln in enumerate(lines) if ln.startswith("name:")), None)
    if name_i is None:
        raise ValueError("tmpl has no top-level 'name:' line")
    try:
        jobs_i = lines.index("jobs:")
    except ValueError:
        raise ValueError("tmpl has no top-level 'jobs:' line")
    block = "\n".join(lines[name_i:jobs_i]).rstrip("\n")
    for key in ("on:", "permissions:", "concurrency:"):
        if key not in lines[name_i:jobs_i]:
            raise ValueError(f"tmpl preamble is missing top-level '{key}'")
    return block


def extract_sarif_upload(tmpl_text: str) -> str:
    """Extract the tmpl mechanical job's SARIF-upload step, verbatim."""
    mech = extract_job(tmpl_text, "mechanical")
    marker = "      - name: Upload SARIF"
    idx = mech.find(marker)
    if idx == -1:
        raise ValueError("tmpl mechanical job has no 'Upload SARIF' step")
    block = mech[idx:].rstrip("\n")
    if "github/codeql-action/upload-sarif@v3" not in block:
        raise ValueError("tmpl SARIF step no longer uses upload-sarif@v3 — re-check slice")
    if "continue-on-error: true" not in block:
        raise ValueError(
            "tmpl SARIF step lost continue-on-error — a SARIF-service outage would block"
        )
    return block


def build_mechanical(tmpl_text: str, profile: Mapping) -> str:
    """Assemble the engine's mechanical job from ENGINE_PROFILE + tmpl slices."""
    if profile["CK_BLOCKING"]:
        ck_step = (
            "      - name: Cathedral Keeper (architecture)\n"
            f"        run: {_CK_CMD}"
        )
    else:
        ck_step = (
            "      # report-only until E0.4/E0.6 land a green path: CK exits 1 on\n"
            "      # >=high findings (236 on 2026-07-06) and is silent without\n"
            "      # --verbose. This is the workflow's ONLY masked step; flip\n"
            "      # ENGINE_PROFILE[\"CK_BLOCKING\"] to True (drops continue-on-error)\n"
            "      # once the >=high findings are baselined or cleared.\n"
            "      - name: Cathedral Keeper (architecture, report-only)\n"
            f"        run: {_CK_CMD}\n"
            "        continue-on-error: true"
        )

    steps = [
        (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          fetch-depth: 0"
        ),
        (
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            f"          python-version: \"{profile['PYTHON_VERSION']}\""
        ),
        (
            "      - name: quality.yml in sync with quality.yml.tmpl + ENGINE_PROFILE\n"
            "        run: python harness/selfci/gen_quality_workflow.py --check"
        ),
        (
            "      - name: Test suites (blocking)\n"
            "        run: make test"
        ),
        (
            f"      - name: {profile['QG_STEP_NAME']}\n"
            f"        run: {profile['QG_CMD']}"
        ),
        ck_step,
        (
            "      - name: Upload CK reports\n"
            "        if: always()\n"
            "        uses: actions/upload-artifact@v4\n"
            "        with:\n"
            "          name: ck-reports\n"
            "          path: |\n"
            "            ck-report.md\n"
            "            ck-report.json\n"
            "        continue-on-error: true"
        ),
        extract_sarif_upload(tmpl_text),
    ]
    header = (
        "  mechanical:\n"
        "    name: Mechanical guardrails\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
    )
    return header + "\n\n".join(steps)


def build_process(tmpl_text: str) -> str:
    """The tmpl's process job with the PR-lint path rewired to the engine's.

    Everything else (env wiring, pull_request guard, setup steps) stays
    verbatim so the engine exercises the same job shape init'd repos get.
    """
    block = extract_job(tmpl_text, "process")
    hits = block.count(_VENDOR_PR_LINT)
    if hits != 1:
        raise ValueError(
            f"tmpl process job references '{_VENDOR_PR_LINT}' {hits} times "
            f"(expected exactly 1) — the path rewire would corrupt the job"
        )
    return block.replace(_VENDOR_PR_LINT, _ENGINE_PR_LINT)


def render(tmpl_text: str, profile: Optional[Mapping] = None) -> str:
    """Render the engine workflow (LF-only) from tmpl text + profile."""
    profile = ENGINE_PROFILE if profile is None else profile
    jobs = [build_mechanical(tmpl_text, profile)]
    if profile["INCLUDE_PROCESS"]:
        jobs.append(build_process(tmpl_text))
    jobs.append(extract_job(tmpl_text, "surface"))
    out = (
        _HEADER
        + "\n"
        + extract_preamble(tmpl_text)
        + "\n\njobs:\n"
        + "\n\n".join(jobs)
        + "\n"
    )
    if "\r" in out:
        raise ValueError("render produced CRLF output — refusing (breaks POSIX CI)")
    return out


def _normalize(text: str) -> str:
    """Strip trailing whitespace per line and trailing blank lines for compare."""
    out = [ln.rstrip() for ln in _norm(text).split("\n")]
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def check_sync(tmpl_text: str, workflow_text: str) -> Tuple[bool, str]:
    """Return (in_sync, message): does the workflow match what render() emits?"""
    expected = render(tmpl_text)
    if _normalize(expected) == _normalize(workflow_text):
        return True, ".github/workflows/quality.yml is in sync with quality.yml.tmpl."
    return (
        False,
        ".github/workflows/quality.yml is OUT OF SYNC with "
        "harness/ci/quality.yml.tmpl + ENGINE_PROFILE. Run "
        "`python harness/selfci/gen_quality_workflow.py` and commit the result.",
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point: write the workflow, or verify it with ``--check``."""
    parser = argparse.ArgumentParser(
        description="Generate/verify .github/workflows/quality.yml from quality.yml.tmpl"
    )
    parser.add_argument("--root", default=None, help="Repo root (default: derived from this file)")
    parser.add_argument("--check", action="store_true",
                        help="Verify sync; exit 1 if stale (no write)")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[2]
    tmpl = root / "harness" / "ci" / "quality.yml.tmpl"
    out = root / ".github" / "workflows" / "quality.yml"

    if not tmpl.exists():
        print(f"[selfci] quality.yml.tmpl not found at {tmpl}", file=sys.stderr)
        return 2

    tmpl_text = tmpl.read_text(encoding="utf-8")
    try:
        rendered = render(tmpl_text)
    except ValueError as exc:
        print(f"[selfci] {exc}", file=sys.stderr)
        return 2

    if args.check:
        existing = out.read_text(encoding="utf-8") if out.exists() else ""
        in_sync, msg = check_sync(tmpl_text, existing)
        print(f"[selfci] {msg}")
        if not in_sync:
            diff = difflib.unified_diff(
                _normalize(existing).split("\n"),
                _normalize(rendered).split("\n"),
                fromfile="committed .github/workflows/quality.yml",
                tofile="rendered from quality.yml.tmpl + ENGINE_PROFILE",
                lineterm="",
            )
            for line in diff:
                print(line)
        return 0 if in_sync else 1

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(rendered)
    print(f"[selfci] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
