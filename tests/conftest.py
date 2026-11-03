"""A local mock of the TeePay API that replays tests/fixtures/fixtures.json."""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES = json.loads((FIXTURES_DIR / "fixtures.json").read_text(encoding="utf-8"))
SANDBOX_KEY = "tp_test_" + "0" * 32 + ".mocksecret"
LIVE_KEY = "tp_live_" + "0" * 32 + ".mocksecret"


def _template_regex(template: str) -> "re.Pattern[str]":
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", template) + "$")


ROUTES = [
    (op["method"], _template_regex(op["path"]), op_id, op)
    for op_id, op in FIXTURES["operations"].items()
]


class MockServer:
    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        self._queue: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence
                pass

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                url = urlsplit(self.path)
                record = {
                    "method": self.command,
                    "path": url.path,
                    "raw_path": url.path,
                    "query": {k: v[0] for k, v in parse_qs(url.query).items()},
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "header_list": list(self.headers.items()),
                    "raw_body": raw,
                    "body": json.loads(raw) if raw else None,
                }
                with server._lock:
                    server.requests.append(record)
                    override = server._queue.pop(0) if server._queue else None
                if override and override.get("drop"):
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                if override and override.get("delay"):
                    time.sleep(override["delay"])
                status, body, headers = server._resolve(self.command, url.path, override)
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("TeePay-Version", "2026-10-18")
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass

            do_GET = _handle
            do_POST = _handle

        class Server(ThreadingHTTPServer):
            def handle_error(self, request: Any, client_address: Any) -> None:
                pass  # clients closing keep-alive / timed-out connections

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def _resolve(self, method: str, path: str, override: Optional[Dict[str, Any]]):  # type: ignore[no-untyped-def]
        default_headers = {"X-Request-ID": "req_mock", "RateLimit-Limit": "120", "RateLimit-Remaining": "119", "RateLimit-Reset": "60"}
        if override and "error" in override:
            err = FIXTURES["errors"][override["error"]]
            headers = {**err.get("headers", {}), **override.get("headers", {})}
            return err["status"], err["body"], headers
        if override and "status" in override:
            return override["status"], override.get("body", {}), {**default_headers, **override.get("headers", {})}
        for route_method, regex, _op_id, op in ROUTES:
            if route_method == method and regex.match(path):
                headers = dict(default_headers)
                if override:
                    headers.update(override.get("headers", {}))
                return op["status"], op["body"], headers
        err = FIXTURES["errors"]["not_found"]
        return err["status"], err["body"], {}

    def queue(self, *responses: Dict[str, Any]) -> None:
        """Next responses, in order. Keys: error=<fixture>, status/body/headers, delay, drop."""
        with self._lock:
            self._queue.extend(responses)

    def wait_for(self, count: int, timeout: float = 5.0) -> int:
        """Wait until ``count`` requests were recorded (handlers can lag behind a client timeout)."""
        deadline = time.time() + timeout
        while len(self.requests) < count and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.05)
        return len(self.requests)

    @property
    def last(self) -> Dict[str, Any]:
        return self.requests[-1]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():  # type: ignore[no-untyped-def]
    mock = MockServer()
    yield mock
    mock.close()


@pytest.fixture
def client(server):  # type: ignore[no-untyped-def]
    from teepay import TeePay

    c = TeePay(SANDBOX_KEY, base_url=server.url, timeout=5)
    yield c
    c.close()


@pytest.fixture
async def aclient(server):  # type: ignore[no-untyped-def]
    from teepay import AsyncTeePay

    c = AsyncTeePay(SANDBOX_KEY, base_url=server.url, timeout=5)
    yield c
    await c.close()
