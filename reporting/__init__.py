"""
Reporting utilities for Quality Gate + Cathedral Keeper HTML reports.
Shared helpers used by generate_html_reports.py and generate_index.py.
"""

import json
import re
from pathlib import Path
from collections import Counter


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------

def load_json(path):
    """Load a JSON file, returning None on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Repository discovery
# ---------------------------------------------------------------------------

def discover_repos(root):
    """Return a list of (repo_dir, qg_path_or_None, ck_path_or_None) tuples.

    Scans *root* for directories that contain a ``.quality-reports/`` folder
    with either ``quality-gate-report.json`` or ``cathedral-keeper/report.json``.

    If *root* itself has ``.quality-reports/``, returns just that single entry
    (single-repo mode).
    """
    root = Path(root).resolve()
    results = []

    # Single-repo mode: root itself has reports
    qg = root / ".quality-reports" / "quality-gate-report.json"
    ck = root / ".quality-reports" / "cathedral-keeper" / "report.json"
    if qg.is_file() or ck.is_file():
        results.append((root, qg if qg.is_file() else None, ck if ck.is_file() else None))
        return results

    # Multi-repo mode: scan immediate subdirectories
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        qg = child / ".quality-reports" / "quality-gate-report.json"
        ck = child / ".quality-reports" / "cathedral-keeper" / "report.json"
        if qg.is_file() or ck.is_file():
            results.append((child, qg if qg.is_file() else None, ck if ck.is_file() else None))

    return results


# ---------------------------------------------------------------------------
# Name / tech inference
# ---------------------------------------------------------------------------

# Pattern: trailing hex hash separated by a dash (e.g. "my_project-a1b2c3d4e5f6")
_HASH_SUFFIX = re.compile(r"-[0-9a-f]{8,}$")

def infer_friendly_name(dirname):
    """Derive a human-readable name from a directory name.

    Strips trailing hex-hash suffixes, replaces underscores/hyphens with spaces,
    and title-cases the result.
    """
    name = dirname
    # Strip trailing hash (common in cloned / exported repos)
    name = _HASH_SUFFIX.sub("", name)
    # Replace separators
    name = name.replace("_", " ").replace("-", " ")
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name else dirname


def infer_tech_stack(qg_data):
    """Guess the technology stack from the file extensions in QG data.

    Returns a short string like 'Python', 'TypeScript / React', 'JavaScript',
    or 'Mixed' if multiple primary languages are found.
    """
    if not qg_data:
        return "Unknown"

    ext_counts = Counter()

    # Count from issues
    for issue in qg_data.get("issues", []):
        f = issue.get("file", "")
        ext = Path(f).suffix.lower()
        if ext:
            ext_counts[ext] += 1

    # Count from PRS keys
    for f in qg_data.get("prs", {}):
        ext = Path(f).suffix.lower()
        if ext:
            ext_counts[ext] += 1

    if not ext_counts:
        return "Unknown"

    py = ext_counts.get(".py", 0)
    ts = ext_counts.get(".ts", 0) + ext_counts.get(".tsx", 0)
    js = ext_counts.get(".js", 0) + ext_counts.get(".jsx", 0)

    parts = []
    if py and py >= ts and py >= js:
        parts.append("Python")
    if ts and ts >= js:
        parts.append("TypeScript")
    elif js:
        parts.append("JavaScript")
    if ext_counts.get(".tsx", 0) or ext_counts.get(".jsx", 0):
        parts.append("React")

    if not parts:
        # Fallback: most common extension
        top_ext = ext_counts.most_common(1)[0][0]
        return top_ext.lstrip(".")
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def health_score(qg_data, ck_data):
    """Compute an overall health score 0-100 from QG stats + CK findings.

    Budget: QG can deduct up to 55 pts, CK can deduct up to 45 pts.
    This prevents double-counting when CK ingests QG results (which
    would make QG issues penalize twice).

    QG budget (max 55):
      - PRS failure rate:  up to 25 pts
      - Error count:       up to 20 pts
      - Warning count:     up to 10 pts

    CK budget (max 45):
      - High/blocker:      up to 25 pts  (capped — excludes QG integration findings)
      - Medium:            up to 15 pts
      - Low (architectural): up to 5 pts (many low findings = structural issues)
    """
    score = 100

    if qg_data:
        stats = qg_data.get("stats", {})
        total_files = stats.get("files_checked", 1) or 1
        failed_prs = stats.get("prs_files_failed", 0)
        errors = stats.get("error", 0)
        warnings = stats.get("warning", 0)
        score -= min((failed_prs / total_files) * 40, 25)
        score -= min(errors * 0.15, 20)
        score -= min(warnings * 0.02, 10)

    if ck_data:
        findings = ck_data.get("findings", [])
        # Exclude QG integration findings from CK deductions to avoid double-counting
        ck_only = [f for f in findings if "quality_gate" not in f.get("policy_id", "")]
        high_count = sum(1 for f in ck_only if f.get("severity") in ("high", "blocker"))
        med_count = sum(1 for f in ck_only if f.get("severity") == "medium")
        low_count = sum(1 for f in ck_only if f.get("severity") == "low")
        total_ck_files = len(set(
            e.get("file", "") for f in ck_only for e in f.get("evidence", [])
        ))
        score -= min(high_count * 2, 25)
        score -= min(med_count * 0.5, 15)
        # Many low findings signal structural issues, but cap the impact
        score -= min(low_count * 0.01, 5)

    return max(0, min(100, round(score)))


def health_color(score):
    """Return a hex color for a health score."""
    if score >= 80:
        return "#16a34a"
    if score >= 60:
        return "#d97706"
    if score >= 40:
        return "#ea580c"
    return "#dc2626"


def grade(score):
    """Return a letter grade A-F for a numeric score."""
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def prs_grade(score):
    """Return (letter, hex_color) tuple for a PRS score."""
    if score >= 95:
        return ("A", "#16a34a")
    if score >= 85:
        return ("B", "#65a30d")
    if score >= 70:
        return ("C", "#d97706")
    if score >= 50:
        return ("D", "#ea580c")
    return ("F", "#dc2626")


def esc(text):
    """HTML-escape a string."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
