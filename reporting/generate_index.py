#!/usr/bin/env python3
"""
Master Quality Dashboard Generator
====================================
Generates an index HTML page with a cross-repository comparison dashboard.
Links to individual per-repo HTML reports produced by generate_html_reports.py.

Usage:
    # Auto-discover repos under a workspace
    python generate_index.py --root /path/to/workspace

    # Explicit repo list
    python generate_index.py --repos /path/repo1 /path/repo2

    # Custom output and title
    python generate_index.py --root . --out ./reports --title "My Project Dashboard"
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if _THIS_DIR not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from __init__ import (  # noqa: E402
    load_json, discover_repos, infer_friendly_name, infer_tech_stack,
    health_score, health_color, grade,
)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Generate a master HTML dashboard aggregating quality reports across repositories."
    )
    p.add_argument("--root", type=str, default=".",
                   help="Workspace directory to scan for repos (default: cwd)")
    p.add_argument("--repos", nargs="+", type=str, default=None,
                   help="Explicit repo directories (skips auto-discovery)")
    p.add_argument("--out", type=str, default=None,
                   help="Output directory for index.html (default: <root>/.quality-reports)")
    p.add_argument("--title", type=str, default="Quality Dashboard",
                   help="Dashboard title")
    args = p.parse_args(argv)

    root = Path(args.root).resolve()

    # Discover repos
    if args.repos:
        repo_entries = []
        for r in args.repos:
            rp = Path(r).resolve()
            qg = rp / ".quality-reports" / "quality-gate-report.json"
            ck = rp / ".quality-reports" / "cathedral-keeper" / "report.json"
            if qg.is_file() or ck.is_file():
                repo_entries.append((rp, qg if qg.is_file() else None, ck if ck.is_file() else None))
            else:
                print(f"  SKIP  {rp.name} (no .quality-reports/ found)")
    else:
        repo_entries = discover_repos(root)

    if not repo_entries:
        print("No repositories with quality reports found.")
        return 1

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for repo_dir, qg_path, ck_path in repo_entries:
        qg = load_json(qg_path) if qg_path else None
        ck = load_json(ck_path) if ck_path else None

        friendly = infer_friendly_name(repo_dir.name)
        tech = infer_tech_stack(qg)
        slug = friendly.lower().replace(" ", "_")

        stats = qg.get("stats", {}) if qg else {}
        hs = health_score(qg, ck)
        prs_data = qg.get("prs", {}) if qg else {}
        scores = [v.get("score", 0) for v in prs_data.values()]
        avg_prs = round(sum(scores) / len(scores), 1) if scores else 0

        rows.append({
            "name": friendly,
            "tech": tech,
            "slug": slug,
            "health": hs,
            "files": stats.get("files_checked", 0),
            "lines": stats.get("lines_checked", 0),
            "errors": stats.get("error", 0),
            "warnings": stats.get("warning", 0),
            "avg_prs": avg_prs,
            "prs_pass": stats.get("prs_files_scored", 0) - stats.get("prs_files_failed", 0),
            "prs_total": stats.get("prs_files_scored", 0),
            "ck_findings": len(ck.get("findings", [])) if ck else 0,
        })

    total_files = sum(r["files"] for r in rows)
    total_lines = sum(r["lines"] for r in rows)
    total_errors = sum(r["errors"] for r in rows)
    total_warnings = sum(r["warnings"] for r in rows)
    avg_health = round(sum(r["health"] for r in rows) / len(rows)) if rows else 0
    repo_count = len(rows)
    title = args.title

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #f8fafc; --card: #ffffff; --border: #e2e8f0;
    --text: #1e293b; --text2: #475569; --text3: #94a3b8;
    --accent: #3b82f6; --green: #16a34a; --red: #dc2626;
    --orange: #ea580c; --yellow: #d97706;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
  }}
  .header {{
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
    color: white; padding: 48px; text-align: center;
  }}
  .header h1 {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; }}
  .header .sub {{ color: #94a3b8; font-size: 15px; margin-top: 4px; }}
  .header .meta {{ color: #64748b; font-size: 12px; margin-top: 12px; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 48px; }}
  .summary {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 32px; }}
  .scard {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px; text-align: center;
  }}
  .scard .val {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; }}
  .scard .lbl {{ font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
  .repo-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; margin-bottom: 32px; }}
  .repo-card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 12px; padding: 24px; transition: box-shadow 0.2s;
    text-decoration: none; color: var(--text); display: block;
  }}
  .repo-card:hover {{ box-shadow: 0 8px 24px rgba(0,0,0,0.08); transform: translateY(-2px); transition: all 0.2s; }}
  .repo-card .rc-top {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }}
  .repo-card .rc-name {{ font-size: 18px; font-weight: 700; }}
  .repo-card .rc-tech {{ font-size: 11px; color: var(--text3); background: #f1f5f9; padding: 2px 8px; border-radius: 4px; }}
  .health-ring {{
    width: 64px; height: 64px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; font-weight: 800; color: white;
  }}
  .rc-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
  .rc-stat {{ text-align: center; }}
  .rc-stat .v {{ font-size: 18px; font-weight: 700; }}
  .rc-stat .l {{ font-size: 10px; color: var(--text3); text-transform: uppercase; }}
  .bar {{ width: 100%; height: 8px; background: #e2e8f0; border-radius: 4px; margin-top: 12px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; }}
  .comparison {{ margin-bottom: 32px; }}
  .comparison h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 16px; border-bottom: 2px solid var(--border); padding-bottom: 8px; }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--card);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 13px;
  }}
  th {{
    background: #f1f5f9; padding: 10px 14px; text-align: left;
    font-weight: 600; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; color: var(--text2); border-bottom: 1px solid var(--border);
  }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #f1f5f9; }}
  tr:hover td {{ background: #f8fafc; }}
  .footer {{ text-align: center; padding: 24px; color: var(--text3); font-size: 12px; border-top: 1px solid var(--border); }}
  @media (max-width: 768px) {{
    .summary {{ grid-template-columns: repeat(2, 1fr); }}
    .repo-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="sub">Cross-Repository Quality &amp; Architecture Overview</div>
  <div class="meta">Generated: {now} &middot; {repo_count} Repository{"" if repo_count == 1 else "ies"} Analyzed</div>
</div>
<div class="container">
  <div class="summary">
    <div class="scard">
      <div class="val" style="color:{health_color(avg_health)}">{avg_health}</div>
      <div class="lbl">Avg Health Score</div>
    </div>
    <div class="scard">
      <div class="val">{total_files}</div>
      <div class="lbl">Files Analyzed</div>
    </div>
    <div class="scard">
      <div class="val">{total_lines:,}</div>
      <div class="lbl">Lines of Code</div>
    </div>
    <div class="scard">
      <div class="val" style="color:var(--red)">{total_errors}</div>
      <div class="lbl">Total Errors</div>
    </div>
    <div class="scard">
      <div class="val" style="color:var(--yellow)">{total_warnings}</div>
      <div class="lbl">Total Warnings</div>
    </div>
  </div>

  <div class="repo-grid">
"""

    for r in sorted(rows, key=lambda x: x["health"]):
        hc = health_color(r["health"])
        prs_pct = round(r["avg_prs"])
        bar_color = "#16a34a" if r["avg_prs"] >= 85 else "#d97706" if r["avg_prs"] >= 70 else "#dc2626"
        html += f"""
    <a class="repo-card" href="quality_report_{r['slug']}.html">
      <div class="rc-top">
        <div>
          <div class="rc-name">{r['name']}</div>
          <span class="rc-tech">{r['tech']}</span>
        </div>
        <div class="health-ring" style="background:{hc}">{r['health']}</div>
      </div>
      <div class="rc-stats">
        <div class="rc-stat"><div class="v">{r['files']}</div><div class="l">Files</div></div>
        <div class="rc-stat"><div class="v" style="color:var(--red)">{r['errors']}</div><div class="l">Errors</div></div>
        <div class="rc-stat"><div class="v" style="color:var(--yellow)">{r['warnings']}</div><div class="l">Warnings</div></div>
        <div class="rc-stat"><div class="v">{r['ck_findings']}</div><div class="l">Arch Issues</div></div>
      </div>
      <div class="bar"><div class="bar-fill" style="width:{prs_pct}%;background:{bar_color}"></div></div>
      <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:11px;color:var(--text3)">
        <span>Avg PRS: {r['avg_prs']}</span>
        <span>PRS Pass: {r['prs_pass']}/{r['prs_total']}</span>
      </div>
    </a>
"""

    html += """
  </div>

  <div class="comparison">
    <h2>Repository Comparison</h2>
    <table>
      <thead>
        <tr>
          <th>Repository</th><th>Tech</th><th>Health</th><th>Grade</th>
          <th>Files</th><th>Lines</th><th>Errors</th><th>Warnings</th>
          <th>Avg PRS</th><th>PRS Pass Rate</th><th>Arch Findings</th>
        </tr>
      </thead>
      <tbody>
"""
    for r in sorted(rows, key=lambda x: -x["health"]):
        hc = health_color(r["health"])
        g = grade(r["avg_prs"])
        pass_rate = round(r["prs_pass"] / r["prs_total"] * 100) if r["prs_total"] else 0
        html += f"""<tr>
  <td><a href="quality_report_{r['slug']}.html" style="color:var(--accent);text-decoration:none;font-weight:600">{r['name']}</a></td>
  <td>{r['tech']}</td>
  <td style="font-weight:700;color:{hc}">{r['health']}</td>
  <td style="font-weight:800">{g}</td>
  <td>{r['files']}</td>
  <td>{r['lines']:,}</td>
  <td style="color:var(--red);font-weight:600">{r['errors']}</td>
  <td style="color:var(--yellow);font-weight:600">{r['warnings']}</td>
  <td>{r['avg_prs']}</td>
  <td>{pass_rate}%</td>
  <td>{r['ck_findings']}</td>
</tr>"""

    html += f"""
      </tbody>
    </table>
  </div>
</div>
<div class="footer">
  {title} &middot; Generated {now} &middot;
  Powered by Quality Gate + Cathedral Keeper
</div>
</body>
</html>"""

    # Write output
    if args.out:
        out_dir = Path(args.out).resolve()
    elif len(repo_entries) == 1:
        out_dir = repo_entries[0][0] / ".quality-reports"
    else:
        out_dir = root / ".quality-reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / "index.html"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Master dashboard generated: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
