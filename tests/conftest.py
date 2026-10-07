"""Shared test setup: a fake Ollama on a real local socket.

pytest loads this file before the tests in this directory, and any fixture
defined here is available to every test by naming it as a parameter.
"""

import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    """A reply captured from a real Ollama server (tests/fixtures/ollama)."""
    return (FIXTURES / "ollama" / name).read_bytes()


@dataclass
class Reply:
    body: bytes
    status: int = 200
    content_type: str = "application/json"


@dataclass
class FakeOllama:
    """What the fake server answers, and what it was asked.

    replies maps a path to its reply; any other path is a 404 in Ollama's
    plain-text style. Requests are recorded rather than asserted on inside the
    server: an assert in the server's thread would fail that thread, not the
    test (the same reason Go's test server may call t.Errorf but not t.Fatalf).
    """

    url: str
    replies: dict[str, Reply] = field(default_factory=lambda: dict[str, Reply]())
    paths: list[str] = field(default_factory=lambda: list[str]())
    bodies: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())

    @property
    def host_port(self) -> str:
        return self.url.removeprefix("http://")


@pytest.fixture
def ollama() -> Iterator[FakeOllama]:
    """A fake Ollama listening on a free port for the length of one test."""
    fake: FakeOllama

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._answer()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            fake.bodies.append(json.loads(self.rfile.read(length)))
            self._answer()

        def _answer(self) -> None:
            fake.paths.append(self.path)
            reply = fake.replies.get(self.path, Reply(b"404 page not found\n", 404, "text/plain"))
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # keep the test output quiet

    # Port 0 asks the operating system for any free port.
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[:2]
    fake = FakeOllama(url=f"http://{host!s}:{port}")
    # shutdown() waits for the serving loop to notice, which it checks every
    # poll_interval: 0.5s by default, per test.
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield fake
    server.shutdown()
    server.server_close()


@pytest.fixture
def dead_url() -> str:
    """A URL nothing listens on: a server is bound to a free port and closed
    before the test uses it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    host, port = server.server_address[:2]
    server.server_close()
    return f"http://{host!s}:{port}"
