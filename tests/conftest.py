"""Shared test setup: a fake Ollama on a real local socket.

pytest loads this file before the tests in this directory, and any fixture
defined here is available to every test by naming it as a parameter.
"""

import json
import select
import socket
import struct
import threading
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own run history, in its own temporary directory.

    autouse: no test can forget it. The first version of milestone 7's tests
    had no such fixture, and the --research tests wrote three fake runs into
    the real ~/.local/state/quantic-agent, as Go's milestone 7 tests once did.
    """
    db = tmp_path / "state" / "agent.db"
    monkeypatch.setenv("QUANTIC_AGENT_DB", str(db))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return db


@pytest.fixture
def anyio_backend() -> str:
    """Async tests (marked anyio) run on asyncio, which the agent uses."""
    return "asyncio"


def fixture(name: str) -> bytes:
    """A reply captured from a real Ollama server (tests/fixtures/ollama)."""
    return (FIXTURES / "ollama" / name).read_bytes()


@dataclass
class Reply:
    """One answer. drop=True closes the connection without replying, the way
    a restarting Ollama does; reset=True aborts it, so the client sees the
    connection reset by its peer; hang=True never answers, as a long
    generation doesn't, until the client gives up. delay is how many seconds
    the answer takes, as a generation does."""

    body: bytes = b""
    status: int = 200
    content_type: str = "application/json"
    drop: bool = False
    reset: bool = False
    hang: bool = False
    delay: float = 0.0


@dataclass
class FakeOllama:
    """What the fake server answers, and what it was asked.

    replies maps a path to its reply, or to a list of replies given in turn,
    the last one repeating; any other path is a 404 in Ollama's plain-text
    style. Requests are recorded rather than asserted on inside the
    server: an assert in the server's thread would fail that thread, not the
    test (the same reason Go's test server may call t.Errorf but not t.Fatalf).
    """

    url: str
    replies: dict[str, Reply | list[Reply]] = field(
        default_factory=lambda: dict[str, Reply | list[Reply]]()
    )
    paths: list[str] = field(default_factory=lambda: list[str]())
    bodies: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    # How many hanging requests the client gave up on by closing the
    # connection, which is how Ollama learns to stop generating.
    hangups: int = 0
    released: threading.Event = field(default_factory=threading.Event)
    # The most requests the server was answering at the same moment.
    peak: int = 0
    _busy: int = 0
    _count: threading.Lock = field(default_factory=threading.Lock)

    def wait_for_hangups(self, n: int, seconds: float = 2) -> bool:
        """Whether n hang-ups were seen within seconds: the server's thread
        notices a closed connection a moment after the client closes it."""
        deadline = time.monotonic() + seconds
        while self.hangups < n and time.monotonic() < deadline:
            time.sleep(0.01)
        return self.hangups >= n

    @contextmanager
    def answering(self) -> Generator[None]:
        """Counts a request as being answered for the length of the block."""
        with self._count:
            self._busy += 1
            self.peak = max(self.peak, self._busy)
        try:
            yield
        finally:
            with self._count:
                self._busy -= 1

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
            with fake.answering():
                self._answer()

        def _answer(self) -> None:
            fake.paths.append(self.path)
            reply = fake.replies.get(self.path, Reply(b"404 page not found\n", 404, "text/plain"))
            if isinstance(reply, list):
                reply = reply.pop(0) if len(reply) > 1 else reply[0]
            if reply.drop:
                # Returning without a response; the server closes the socket.
                self.close_connection = True
                return
            if reply.hang:
                self._wait_for_hangup()
                return
            if reply.delay:
                time.sleep(reply.delay)
            if reply.reset:
                # Lingering for zero seconds makes close() send a TCP reset.
                self.connection.setsockopt(
                    socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                )
                self.connection.close()
                return
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def _wait_for_hangup(self) -> None:
            # Readable with nothing to read means the client closed its end.
            while not fake.released.is_set():
                readable, _, _ = select.select([self.connection], [], [], 0.01)
                if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
                    fake.hangups += 1
                    return
            self.close_connection = True

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
    fake.released.set()  # let any request still hanging go
    server.shutdown()
    server.server_close()


# An address nothing listens on, as with a stopped Ollama. Port 1 is
# privileged and outside the range the system hands out. The port of a server
# just closed isn't safe for this: another process can be given it a moment
# later, and then the "dead" server answers.
DEAD_URL = "http://127.0.0.1:1"


@dataclass
class FakeMCP:
    """A fake Quantic MCP server, enough of Streamable HTTP for the real SDK.

    It answers by JSON-RPC method with replies captured from quantic.finance
    (tests/fixtures/mcp), rewriting each reply's id to the request's. tools
    maps a tool name to the fixture its tools/call answers with, or to "hang"
    for a call that never answers; requests records every JSON-RPC message
    received, in order. rate_limited is how many POSTs to refuse first with
    429, the way Quantic refuses an anonymous caller over its limit.
    """

    url: str
    tools: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    rate_limited: int = 0
    requests: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    released: threading.Event = field(default_factory=threading.Event)

    def calls(self) -> list[dict[str, Any]]:
        """The params of every tools/call received."""
        return [r["params"] for r in self.requests if r.get("method") == "tools/call"]


def _with_id(fixture_text: str, request_id: object) -> str:
    """A captured reply, JSON or one SSE event, answering request_id instead."""
    if fixture_text.lstrip().startswith("{"):
        message = json.loads(fixture_text)
        message["id"] = request_id
        return json.dumps(message)
    lines: list[str] = []
    for line in fixture_text.splitlines():
        if line.startswith("data: "):
            message = json.loads(line.removeprefix("data: "))
            message["id"] = request_id
            line = "data: " + json.dumps(message)
        lines.append(line)
    return "\n".join(lines) + "\n\n"


@pytest.fixture
def quantic_mcp() -> Iterator[FakeMCP]:
    """A fake MCP server on a free port for the length of one test."""
    fake: FakeMCP

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            message: dict[str, Any] = json.loads(self.rfile.read(length))
            if fake.rate_limited > 0:
                fake.rate_limited -= 1
                # Quantic's reply, from QuanticWeb.Plugs.McpAuth.
                body = json.dumps({"error": "rate limited — try again shortly"}).encode()
                self._reply(429, body, "application/json")
                return
            fake.requests.append(message)
            method = message.get("method", "")
            if "id" not in message:  # a notification: acknowledged, no reply
                self._reply(202, b"", "application/json")
                return
            name = {
                "initialize": "initialize.sse",
                "tools/list": "tools-list.json",
                "tools/call": fake.tools.get(message.get("params", {}).get("name", ""), ""),
            }.get(method, "")
            if name == "hang":
                fake.released.wait(5)  # set at teardown
                return
            text = (FIXTURES / "mcp" / name).read_text() if name else ""
            if not text:
                text = (
                    '{"jsonrpc":"2.0","id":0,"error":{"code":-32601,"message":"Method not found"}}'
                )
            body = _with_id(text, message["id"]).encode()
            kind = "text/event-stream" if name.endswith(".sse") else "application/json"
            self._reply(200, body, kind)

        def do_GET(self) -> None:
            # No server-initiated stream: the spec allows refusing it.
            self._reply(405, b"", "text/plain")

        def do_DELETE(self) -> None:
            self._reply(200, b"", "text/plain")

        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Mcp-Session-Id", "test-session")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[:2]
    fake = FakeMCP(url=f"http://{host!s}:{port}/mcp")
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield fake
    fake.released.set()
    server.shutdown()
    server.server_close()
