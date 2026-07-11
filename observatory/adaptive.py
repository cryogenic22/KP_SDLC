"""Future-facing composition of harness telemetry, repository signals, and maturity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .maturity import MaturityEngine
from .plugin import ObservatoryPlugin
from .telemetry import ClaudeCodeTelemetryAdapter, TelemetryAdapter


class AdaptiveObservatory:
    plugin_id = "kp-sdlc/adaptive-observatory@1"

    def __init__(self, root: Path, *, telemetry_adapters: list[TelemetryAdapter] | None = None,
                 memory_adapters=None):
        self.root = root.resolve()
        self.telemetry_adapters = telemetry_adapters or [ClaudeCodeTelemetryAdapter(self.root)]
        self.base = ObservatoryPlugin(self.root, memory_adapters=memory_adapters)
        self.maturity_engine = MaturityEngine(self.root)

    def snapshot(self) -> dict[str, Any]:
        snapshot = self.base.snapshot()
        telemetry = [adapter.probe() for adapter in self.telemetry_adapters]
        snapshot["plugin"] = self.plugin_id
        snapshot["telemetry"] = telemetry
        snapshot["maturity"] = self.maturity_engine.evaluate(snapshot, telemetry)
        return snapshot

    def record_maturity(self) -> tuple[Path, bool]:
        return self.maturity_engine.record(self.snapshot()["maturity"])

