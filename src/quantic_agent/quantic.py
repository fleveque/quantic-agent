"""The client for Quantic's MCP server, the only source of financial facts the
agent is allowed (design N1).

The official MCP SDK speaks the protocol: JSON-RPC over Streamable HTTP,
replies as JSON or as a Server-Sent Events stream, the session the server
opens. This module adds what the agent needs on top of it: an anonymous
connection, one result type, and failures sorted into kinds the research loop
acts on differently.

The agent connects anonymously. Quantic's public reference tools
(dividend_calendar, get_stock, screen_stocks, ...) answer anonymous callers,
rate limited; the tools that read a user's portfolio refuse them. An anonymous
agent therefore cannot reach anyone's data, which enforces design N4 on the
server rather than trusting the agent to behave (decision 0006).

Like the model client, it sets no timeout of its own: callers bound calls with
asyncio.timeout, and a cancellation ends the request in flight, or the wait
before a retry.
"""

import asyncio
import json
import random
from collections.abc import Callable, Iterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Self, cast

import httpx2
import mcp
from mcp import types
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ValidationError

from quantic_agent import network

DEFAULT_URL = "https://quantic.finance/mcp"


class ToolServerError(Exception):
    """Anything that went wrong talking to the MCP server."""


class ToolServerUnavailableError(ToolServerError):
    """No reply came back because the server wasn't there to give one, by the
    same rule as the model server's (network.unreachable)."""


class RateLimitedError(ToolServerError):
    """The server kept answering 429 Too Many Requests until the retries ran
    out. Anonymous callers get 60 requests a minute per IP address (decision
    0006): nothing was wrong with the request, and it can be made again later."""


class RPCError(ToolServerError):
    """The server understood the request and refused it at the protocol level,
    such as an unknown tool or an argument of the wrong type (-32602). It
    describes a mistake in the request, so the research loop hands it back to
    the model to correct.

    detail is the server's explanation, such as 'days: expected type of
    :integer received "ten" value'.
    """

    def __init__(self, code: int, message: str, detail: str) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        text = f"{message} ({code})"
        super().__init__(f"{text}: {detail}" if detail else text)


@dataclass(frozen=True)
class Result:
    """What a tool returned. text is the tool's output, which for Quantic's
    tools is itself a JSON document, to be decoded a second time. is_error
    means the tool ran and refused (a portfolio tool called anonymously, say);
    text then explains why. Neither is an exception: both are answers to hand
    back to the model."""

    text: str
    is_error: bool


@dataclass(frozen=True)
class ToolInfo:
    """One tool the server offers, as it describes it."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Backoff:
    """How a request the server refused with 429 is retried: waits that double
    from base up to max seconds, each with jitter, for at most attempts tries
    in all.

    The defaults outlast Quantic's rate limit. It counts requests in fixed
    one-minute windows and says nothing about when the window ends (no
    Retry-After header), so a refused client may have to wait up to a minute.
    With jitter, these waits add up to between 60.5 and 121 seconds: even the
    shortest schedule outlasts a window.
    """

    attempts: int = 9  # tries in all, the first included; 1 means never retry
    base: float = 1.0
    max: float = 30.0

    def wait(self, retry: int, rand: Callable[[], float] = random.random) -> float:
        """The pause before retry number retry (1 for the first): "equal
        jitter", half the doubled wait plus a random part of the other half.
        Clients refused together don't all come back together, and none comes
        back sooner than half the schedule. rand returns a float in [0, 1)."""
        # Python's ints don't overflow, but 2 ** 1100 is too large to become
        # a float. Past 2 ** 64 the step is long since capped anyway.
        step = min(self.base * 2 ** min(retry - 1, 64), self.max)
        return step / 2 + rand() * step / 2


DEFAULT_BACKOFF = Backoff()

# Called before each retry's wait with the JSON-RPC method, the retry's number
# and the wait in seconds, so the operator sees why a run has gone quiet.
type OnRetry = Callable[[str, int, float], None]


# The JSON-RPC error code a request gets when the retries are spent: one of
# the codes from -32000 to -32099 that JSON-RPC leaves to implementations.
_RATE_LIMITED = -32029


class _RetryRateLimited(httpx2.AsyncBaseTransport):
    """An HTTP transport that retries a POST the server refused with 429,
    after a pause (Backoff).

    It sits under the SDK, because the SDK has no retry of its own: it turns
    a 429 into a JSON-RPC error, "Server returned an error response"
    (-32603), indistinguishable from a request the server rejected, and
    drops a refused notification without a word.

    When the attempts are spent, it answers the request itself, with a
    JSON-RPC error whose code is _RATE_LIMITED, which the SDK hands to the
    caller like any error from the server. Raising here would be worse: the
    SDK runs requests in a task group, so the caller would see its call
    cancelled, which reads as Ctrl-C, and the real error only when the session
    closes.

    Only POSTs carry JSON-RPC messages, and every tool the agent may call only
    reads, so sending one twice can't do anything twice. Nothing else is
    retried: an unreachable server is the caller's to handle (design §3.6),
    and closing a session (a DELETE) shouldn't wait for minutes.
    """

    def __init__(self, backoff: Backoff, on_retry: OnRetry | None) -> None:
        self._inner = httpx2.AsyncHTTPTransport()
        self._backoff = backoff
        self._on_retry = on_retry

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        attempts = max(self._backoff.attempts, 1)
        retry = 0
        while True:
            response = await self._inner.handle_async_request(request)
            if response.status_code != 429 or request.method != "POST":
                return response
            # Read the short body to the end, so the connection can be reused.
            await response.aread()
            await response.aclose()
            retry += 1
            message = _message(request)
            method = str(message.get("method", "?"))
            if retry == attempts:
                reason = f"{method}: 429 Too Many Requests ({attempts} attempts)"
                error = {"code": _RATE_LIMITED, "message": reason}
                reply = {"jsonrpc": "2.0", "id": message.get("id"), "error": error}
                return httpx2.Response(429, json=reply, request=request)
            wait = self._backoff.wait(retry)
            if self._on_retry is not None:
                self._on_retry(method, retry, wait)
            # A cancellation (Ctrl-C, the run's deadline) ends the wait at once.
            await asyncio.sleep(wait)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _message(request: httpx2.Request) -> dict[str, Any]:
    """The JSON-RPC message a request carries, or {} if it isn't one."""
    try:
        message = json.loads(request.content)
    except ValueError:
        return {}
    return cast(dict[str, Any], message) if isinstance(message, dict) else {}


class Server:
    """A session with one MCP server, opened by `async with Server(url)`."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        *,
        backoff: Backoff | None = None,
        on_retry: OnRetry | None = None,
    ) -> None:
        """backoff is how a 429 is retried: DEFAULT_BACKOFF unless given."""
        self.url = url
        # The timeouts the SDK gives its own client (30s, and 300s to read,
        # since a server may hold a stream open), with the retrying transport
        # under them.
        self._http = httpx2.AsyncClient(
            timeout=httpx2.Timeout(30.0, read=300.0),
            transport=_RetryRateLimited(backoff or DEFAULT_BACKOFF, on_retry),
        )
        info = types.Implementation(name="quantic-agent", version=version("quantic-agent"))
        # mode="legacy" goes straight to the initialize handshake, which is what
        # Quantic's server speaks. The default, "auto", first probes with a
        # newer server/discover request and falls back: one wasted request per
        # session, against a limit of 60 a minute.
        self._client = mcp.Client(
            streamable_http_client(url, http_client=self._http), client_info=info, mode="legacy"
        )
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> Self:
        # The handshake: the SDK announces the client, negotiates the protocol
        # version, and records the session the server opens. The HTTP client
        # is ours, so ours to close, after the session.
        await self._stack.enter_async_context(self._http)
        try:
            await self._stack.enter_async_context(self._client)
        except Exception as err:
            await self._stack.aclose()
            raise _failure(f"connecting to {self.url}", err) from err
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._stack.__aexit__(*exc_info)

    async def list_tools(self) -> list[ToolInfo]:
        """The tools the server offers."""
        try:
            listed = await self._client.list_tools()
        except Exception as err:
            raise _failure("tools/list", err) from err
        return [
            ToolInfo(name=t.name, description=t.description or "", input_schema=t.input_schema)
            for t in listed.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Result:
        """Calls one tool. A refusal by the tool is a Result with is_error; a
        request the server rejects is an RPCError."""
        try:
            result = await self._client.call_tool(name, arguments)
        except mcp.MCPError as err:
            if err.code == _RATE_LIMITED:
                raise RateLimitedError(err.error.message) from err
            raise RPCError(err.code, err.error.message, _detail(err.error.data)) from err
        except Exception as err:
            raise _failure(f"tools/call {name}", err) from err

        # A result is a list of content blocks; Quantic's tools return one text
        # block. Joining the text blocks keeps that exact and copes with more.
        text = "".join(b.text for b in result.content if isinstance(b, types.TextContent))
        return Result(text=text, is_error=result.is_error)


class _ErrorData(BaseModel):
    message: str = ""


def _detail(data: object) -> str:
    """The server's explanation in a JSON-RPC error's data, if it gave one."""
    try:
        return _ErrorData.model_validate(data).message
    except ValidationError:
        return ""


def _leaves(err: BaseException) -> Iterator[BaseException]:
    """The exceptions inside err, however deeply grouped. The SDK runs its
    transport in anyio task groups, so a connection that fails comes back as an
    ExceptionGroup around the real error."""
    if isinstance(err, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], err)
        for inner in group.exceptions:
            yield from _leaves(inner)
    else:
        yield err


def _failure(what: str, err: BaseException) -> ToolServerError:
    leaves = list(_leaves(err))
    kind = ToolServerError
    if any(isinstance(leaf, mcp.MCPError) and leaf.code == _RATE_LIMITED for leaf in leaves):
        kind = RateLimitedError
    elif any(network.unreachable(leaf) for leaf in leaves):
        kind = ToolServerUnavailableError
    return kind(f"{what}: {'; '.join(str(leaf) for leaf in leaves)}")
