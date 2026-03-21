from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from cathedral_keeper.integrations.types import IntegrationContext
from cathedral_keeper.models import Evidence, Finding, clamp_snippet


def run_external_findings_json(ctx: IntegrationContext, cfg: Dict[str, Any]) -> List[Finding]:
    """
    Generic integration for SDLC tooling.

    Contract: run a command that prints JSON to stdout in either form:
      - {"findings": [<FindingDict>, ...]}
      - [<FindingDict>, ...]

    `FindingDict` fields are CK's schema:
      policy_id, title, severity, confidence, why_it_matters, evidence[], fix_options[], verification[], metadata

    The command receives:
      CK_ROOT, CK_PATHS_FILE env vars
    """
    argv = _argv(cfg)
    if not argv:
        return []
    cwd = _cwd(ctx.root, cfg.get("cwd"))
    env = dict(**_base_env(ctx))
    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, env=env)
        raw = proc.stdout.decode("utf-8", errors="ignore") if proc.stdout else ""
        if not raw.strip():
            return []
        data = json.loads(raw)
    except Exception:
        return []
    return _parse_findings(data)


def _argv(cfg: Dict[str, Any]) -> List[str]:
    argv = cfg.get("argv")
    if not isinstance(argv, list) or not argv:
        return []
    out: List[str] = []
    for x in argv:
        s = str(x).strip()
        if s:
            out.append(s)
    return out


def _cwd(root: Path, value: Any) -> Path:
    if not value:
        return root
    p = Path(str(value))
    return (root / p).resolve() if not p.is_absolute() else p


def _base_env(ctx: IntegrationContext) -> Dict[str, str]:
    return {
        "CK_ROOT": str(ctx.root),
        "CK_PATHS_FILE": str(ctx.target_paths_file),
    }


def _parse_findings(data: Any) -> List[Finding]:
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        raw = data.get("findings")
    elif isinstance(data, list):
        raw = data
    else:
        return []
    out: List[Finding] = []
    for item in raw[:2000]:
        f = _finding_from_dict(item)
        if f:
            out.append(f)
    return out


def _finding_from_dict(item: Any) -> Optional[Finding]:
    if not isinstance(item, dict):
        return None
    policy_id = str(item.get("policy_id") or "").strip()
    title = str(item.get("title") or "").strip()
    if not policy_id or not title:
        return None
    sev = str(item.get("severity") or "medium").strip().lower()
    conf = str(item.get("confidence") or "medium").strip().lower()
    why = str(item.get("why_it_matters") or "").strip()
    ev = _evidence_list(item.get("evidence"))
    fix = [str(x) for x in (item.get("fix_options") or []) if str(x).strip()]
    ver = [str(x) for x in (item.get("verification") or []) if str(x).strip()]
    meta = dict(item.get("metadata") or {}) if isinstance(item.get("metadata"), dict) else {}
    return Finding(
        policy_id=policy_id,
        title=title,
        severity=sev,
        confidence=conf,
        why_it_matters=why,
        evidence=ev,
        fix_options=fix,
        verification=ver,
        metadata=meta,
    )


def _evidence_list(raw: Any) -> List[Evidence]:
    if not isinstance(raw, list):
        return []
    out: List[Evidence] = []
    for item in raw[:20]:
        if not isinstance(item, dict):
            continue
        file = str(item.get("file") or "").strip()
        if not file:
            continue
        try:
            line = int(item.get("line") or 1)
        except Exception:
            line = 1
        snippet = clamp_snippet(str(item.get("snippet") or ""))
        note = str(item.get("note") or "").strip()
        out.append(Evidence(file=file, line=line, snippet=snippet, note=note))
    return out

