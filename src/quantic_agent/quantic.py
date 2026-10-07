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
asyncio.timeout, and a cancellation ends the request in flight.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Self, cast

import mcp
from mcp import types
from pydantic import BaseModel, ValidationError

from quantic_agent import network

DEFAULT_URL = "https://quantic.finance/mcp"


class ToolServerError(Exception):
    """Anything that went wrong talking to the MCP server."""


class ToolServerUnavailableError(ToolServerError):
    """No reply came back because the server wasn't there to give one, by the
    same rule as the model server's (network.unreachable)."""


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


class Server:
    """A session with one MCP server, opened by `async with Server(url)`."""

    def __init__(self, url: str = DEFAULT_URL) -> None:
        self.url = url
        info = types.Implementation(name="quantic-agent", version=version("quantic-agent"))
        # mode="legacy" goes straight to the initialize handshake, which is what
        # Quantic's server speaks. The default, "auto", first probes with a
        # newer server/discover request and falls back: one wasted request per
        # session, against a limit of 60 a minute.
        self._client = mcp.Client(url, client_info=info, mode="legacy")

    async def __aenter__(self) -> Self:
        # The handshake: the SDK announces the client, negotiates the protocol
        # version, and records the session the server opens.
        try:
            await self._client.__aenter__()
        except Exception as err:
            raise _failure(f"connecting to {self.url}", err) from err
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self._client.__aexit__(*exc_info)

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
    kind = (
        ToolServerUnavailableError
        if any(network.unreachable(leaf) for leaf in leaves)
        else ToolServerError
    )
    return kind(f"{what}: {'; '.join(str(leaf) for leaf in leaves)}")
