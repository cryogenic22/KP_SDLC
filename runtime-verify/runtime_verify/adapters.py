"""Adapter protocol + registry for runtime-verify.

An adapter resolves a metric's ``source.system`` to a concrete fetcher and
returns the authoritative value at ``source.ref``. Resolution fails closed: an
unregistered system raises ``AdapterUnresolved`` (a named error, never a silent
skip) and a missing ref raises ``AdapterError`` (never a silent ``None``).

``StubAdapter`` is a deterministic, in-repo fixture adapter keyed by ref, so the
spine and its tests run with zero external dependencies. The real SQL-warehouse
adapter (D3) lands in a later PR; this module only fixes the protocol and the
registry so that adapter drops in cleanly.
"""

from __future__ import annotations

from typing import Protocol


class AdapterError(Exception):
    """A resolved adapter could not produce a value for a ref (fail closed)."""


class AdapterUnresolved(Exception):
    """No adapter is registered for a metric's source.system (fail closed)."""


class AdapterProtocol(Protocol):
    """Fetch the authoritative value (a scalar, or a row iterator for grain
    uniqueness in a later pack) at an adapter-interpreted locator ``ref``."""

    def fetch(self, ref: str) -> object:
        ...


class StubAdapter:
    """Deterministic in-repo adapter: fixture values keyed by ref."""

    def __init__(self, values: dict | None = None) -> None:
        self._values = dict(values or {})

    def fetch(self, ref: str) -> object:
        if ref not in self._values:
            raise AdapterError(f"stub adapter has no value for ref {ref!r}")
        return self._values[ref]


class AdapterRegistry:
    """Maps a metric ``source.system`` name to a concrete adapter."""

    def __init__(self) -> None:
        self._adapters: dict = {}

    def register(self, system: str, adapter: AdapterProtocol) -> None:
        self._adapters[system] = adapter

    def get(self, system: str):
        """The adapter for ``system``, or ``None`` if none is registered.

        The non-raising sibling of ``resolve`` -- a caller that wants to turn an
        unresolved system into its own fail-closed finding uses this instead of
        catching an exception."""
        return self._adapters.get(system)

    def resolve(self, system: str) -> AdapterProtocol:
        adapter = self._adapters.get(system)
        if adapter is None:
            raise AdapterUnresolved(f"no adapter registered for system {system!r}")
        return adapter
