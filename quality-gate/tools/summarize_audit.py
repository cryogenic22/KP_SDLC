#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    else:
        text = raw.decode("utf-8")
    return json.loads(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize quality-gate --json output.")
    parser.add_argument("report", type=Path, help="Path to a JSON report from quality-gate --json")
    parser.add_argument("--top", type=int, default=15, help="Top N rules/files to show")
    args = parser.parse_args()

    data = _load(args.report)
    issues = list(data.get("issues", []) or [])
    stats = dict(data.get("stats", {}) or {})
    prs = dict(data.get("prs", {}) or {})

    by_rule = Counter(i.get("rule") for i in issues if i.get("rule"))
    by_sev = Counter(i.get("severity") for i in issues if i.get("severity"))
    by_file = Counter(i.get("file") for i in issues if i.get("file"))

    rule_sev: dict[str, Counter[str]] = defaultdict(Counter)
    for i in issues:
        rule = i.get("rule")
        sev = i.get("severity")
        if rule and sev:
            rule_sev[str(rule)][str(sev)] += 1

    scores: list[float] = []
    for v in prs.values():
        try:
            scores.append(float(v.get("score")))
        except Exception:
            continue

    print("QUALITY GATE SUMMARY")
    print(f"- Files scored: {len(prs)}")
    if scores:
        print(f"- PRS min: {min(scores):.1f}")
    if "prs_min_score" in stats:
        print(f"- PRS threshold: {stats.get('prs_min_score')}")
    print(f"- Issues: {len(issues)} ({dict(by_sev)})")
    print()

    print(f"Top {args.top} rules:")
    for rule, count in by_rule.most_common(args.top):
        sev_counts = dict(rule_sev.get(rule, {}))
        print(f"- {rule}: {count} {sev_counts}")
    print()

    print(f"Top {args.top} files:")
    for file, count in by_file.most_common(args.top):
        print(f"- {file}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
