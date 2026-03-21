from __future__ import annotations

from typing import Any, Callable, Dict, List

from cathedral_keeper.integrations.external_findings_json import run_external_findings_json
from cathedral_keeper.integrations.quality_gate import run_quality_gate
from cathedral_keeper.integrations.types import IntegrationContext
from cathedral_keeper.models import Finding

Runner = Callable[[IntegrationContext, Dict[str, Any]], List[Finding]]


def get_integration_runners() -> Dict[str, Runner]:
    return {
        "quality_gate": run_quality_gate,
        "external_findings_json": run_external_findings_json,
    }


def run_integration(*, ctx: IntegrationContext, integration_id: str, cfg: Dict[str, Any]) -> List[Finding]:
    runners = get_integration_runners()
    runner = runners.get(str(integration_id))
    if not runner:
        return []
    return runner(ctx, cfg)

