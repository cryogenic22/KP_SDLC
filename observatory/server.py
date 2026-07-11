"""Local-only HTTP dashboard for the Observatory snapshot.

One server serves every projection. It takes a *snapshot provider* — any
zero-argument callable returning the snapshot dict (base health, plugin, or the
adaptive composition) — so the transport is decoupled from what is projected.
The provider is cached for a short TTL so the three-second dashboard poll never
re-scans the repository on every request.

Safety: the socket binds to loopback only; ``/api/snapshot`` returns data-only
JSON and ``/`` serves the static dashboard, whose client renders all event
content as DOM text nodes (never injected as HTML).
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
SnapshotProvider = Callable[[], dict[str, Any]]


class SnapshotCache:
    """Thread-safe TTL cache in front of an expensive snapshot provider."""

    def __init__(self, provider: SnapshotProvider, ttl_seconds: float = 2.0):
        self._provider = provider
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._created = 0.0
        self._value: dict[str, Any] | None = None

    def get(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if self._value is None or now - self._created >= self._ttl_seconds:
                self._value = self._provider()
                self._created = now
            return self._value


def _dashboard_bytes() -> bytes:
    return (Path(__file__).parent / "static" / "index.html").read_bytes()


def _make_handler(cache: SnapshotCache, dashboard: bytes) -> type[BaseHTTPRequestHandler]:
    """Bind the cache and dashboard bytes onto a request handler class."""

    class Handler(BaseHTTPRequestHandler):
        _cache = cache
        _dashboard = dashboard

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlparse(self.path).path
            if path == "/api/snapshot":
                self._send(json.dumps(self._cache.get()).encode("utf-8"),
                           "application/json; charset=utf-8")
            elif path in {"/", "/index.html"}:
                self._send(self._dashboard, "text/html; charset=utf-8")
            else:
                self.send_error(404)

        def _send(self, body: bytes, content_type: str):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, message: str, *args: Any):
            print(f"[observatory] {self.address_string()} {message % args}")

    return Handler


def serve(provider: SnapshotProvider, *, root: Path | None = None,
          host: str = "127.0.0.1", port: int = 8765) -> None:
    """Serve the dashboard until interrupted, then shut down explicitly.

    A ``KeyboardInterrupt`` (Ctrl-C) is reported and drains cleanly rather than
    being silently swallowed, so an operator always sees why the server stopped.
    """
    if host not in _LOCAL_HOSTS:
        raise ValueError("Observatory binds to localhost only; remote access "
                         "needs an authenticated deployment design.")
    cache = SnapshotCache(provider)
    server = ThreadingHTTPServer((host, port), _make_handler(cache, _dashboard_bytes()))
    if root is not None:
        print(f"[observatory] watching {root}")
    print(f"[observatory] dashboard http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[observatory] keyboard interrupt received; shutting down")
    finally:
        server.server_close()
        print("[observatory] server stopped cleanly")
