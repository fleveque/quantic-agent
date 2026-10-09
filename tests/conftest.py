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

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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
    for a call that never answers; "name:SYMBOL" answers a call with that
    symbol argument, ahead of the name alone; requests records every JSON-RPC message
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


def tool_result(name: str) -> str:
    """The tool output inside a captured tools/call reply (tests/fixtures/mcp):
    the JSON document in its first content item's text."""
    for line in (FIXTURES / "mcp" / name).read_text().splitlines():
        if line.startswith("data: "):
            return json.loads(line.removeprefix("data: "))["result"]["content"][0]["text"]
    raise ValueError(f"{name} has no data line")


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
            params: dict[str, Any] = message.get("params", {})
            tool = params.get("name", "")
            symbol = params.get("arguments", {}).get("symbol")
            name = {
                "initialize": "initialize.sse",
                "tools/list": "tools-list.json",
                "tools/call": fake.tools.get(f"{tool}:{symbol}", fake.tools.get(tool, "")),
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


@dataclass
class FakeGitHub:
    """A fake GitHub REST API, enough for one App installation on one
    repository, answering with payloads captured from api.github.com
    (tests/fixtures/github). It checks the App's JWT against public_key and
    the installation token on every repository request, keeps the
    repository's refs, and records every request as (method, path, body,
    authorization). pulls maps a pull request's number to the state GET
    answers with: "open", "merged" or "closed"."""

    url: str
    public_key: str
    repo: str = "fleveque/quantic"
    refs: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    pulls: dict[int, str] = field(default_factory=lambda: dict[int, str]())
    requests: list[tuple[str, str, Any, str]] = field(
        default_factory=lambda: list[tuple[str, str, Any, str]]()
    )
    token: str = "ghs_installationtoken"
    token_lifetime: float = 3600.0
    tokens_issued: int = 0


def github_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "github" / name).read_text())


@pytest.fixture(scope="session")
def app_key() -> tuple[str, str]:
    """An RSA key pair for a test GitHub App, as PEM: (private, public)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


@pytest.fixture
def github_api(app_key: tuple[str, str]) -> Iterator[FakeGitHub]:
    """A fake GitHub on a free port for the length of one test."""
    fake: FakeGitHub
    created = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._answer("GET")

        def do_POST(self) -> None:
            self._answer("POST")

        def do_PATCH(self) -> None:
            self._answer("PATCH")

        def do_PUT(self) -> None:
            self._answer("PUT")

        def do_DELETE(self) -> None:
            self._answer("DELETE")

        def _answer(self, method: str) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else None
            auth = self.headers.get("Authorization", "")
            fake.requests.append((method, self.path, body, auth))
            status, reply = self._route(method, self.path, body, auth)
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _route(self, method: str, path: str, body: Any, auth: str) -> tuple[int, Any]:
            bearer = auth.removeprefix("Bearer ")
            repo = f"/repos/{fake.repo}"
            installation = github_fixture("installation.json")
            if path in (
                f"{repo}/installation",
                f"/app/installations/{installation['id']}/access_tokens",
            ):
                try:
                    jwt.decode(bearer, fake.public_key, algorithms=["RS256"])
                except jwt.PyJWTError:
                    return 401, github_fixture("wrong-key.json")
                if method == "GET":
                    return 200, installation
                fake.tokens_issued += 1
                reply = github_fixture("access-token.json")
                reply["token"] = fake.token
                reply["expires_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + fake.token_lifetime)
                )
                return 201, reply
            if not path.startswith(f"{repo}/"):
                return 404, github_fixture("not-found.json")
            if bearer != fake.token:
                return 401, {"message": "Bad credentials"}
            rest = path.removeprefix(f"{repo}/")
            return self._repo(method, rest, body)

        def _repo(self, method: str, rest: str, body: Any) -> tuple[int, Any]:
            if method == "GET" and rest.startswith("git/ref/heads/"):
                ref = "refs/heads/" + rest.removeprefix("git/ref/heads/")
                if ref not in fake.refs:
                    return 404, github_fixture("not-found.json")
                reply = github_fixture("ref.json")
                reply["ref"], reply["object"]["sha"] = ref, fake.refs[ref]
                return 200, reply
            if method == "GET" and rest.startswith("git/commits/"):
                reply = github_fixture("commit.json")
                reply["sha"] = rest.removeprefix("git/commits/")
                return 200, reply
            if method == "POST" and rest == "git/trees":
                created["n"] += 1
                reply = github_fixture("tree.json")
                reply["sha"] = f"tree{created['n']:036d}"
                return 201, reply
            if method == "POST" and rest == "git/commits":
                created["n"] += 1
                reply = github_fixture("commit.json")
                reply["sha"] = f"commit{created['n']:034d}"
                reply["tree"]["sha"] = body["tree"]
                return 201, reply
            if method == "POST" and rest == "git/refs":
                if body["ref"] in fake.refs:
                    return 422, github_fixture("ref-exists.json")
                fake.refs[body["ref"]] = body["sha"]
                reply = github_fixture("ref.json")
                reply["ref"], reply["object"]["sha"] = body["ref"], body["sha"]
                return 201, reply
            if method == "POST" and rest == "pulls":
                number = 100 + len(fake.pulls)
                fake.pulls[number] = "open"
                return 201, self._pull(number, body["head"])
            if method == "GET" and rest.startswith("pulls/"):
                number = int(rest.removeprefix("pulls/"))
                if number not in fake.pulls:
                    return 404, github_fixture("not-found.json")
                return 200, self._pull(number, "agent/x")
            return 404, github_fixture("not-found.json")

        def _pull(self, number: int, head: str) -> dict[str, Any]:
            reply = github_fixture("pull-merged.json")
            state = fake.pulls[number]
            reply["number"] = number
            reply["html_url"] = f"https://github.com/{fake.repo}/pull/{number}"
            reply["head"]["ref"] = head
            reply["state"] = "open" if state == "open" else "closed"
            if state != "merged":
                reply["merged_at"] = None
            return reply

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[:2]
    fake = FakeGitHub(url=f"http://{host!s}:{port}", public_key=app_key[1])
    fake.refs["refs/heads/main"] = github_fixture("ref.json")["object"]["sha"]
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield fake
    server.shutdown()
    server.server_close()
