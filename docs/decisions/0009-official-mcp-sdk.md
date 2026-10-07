# 0009 — Talk to Quantic through the official MCP SDK

**Status:** accepted · **Date:** 2026-10-07

## Context

Milestone 5 connects the agent to Quantic's MCP server. The Go version had no SDK to use and wrote
its client by hand: about 300 lines of JSON-RPC 2.0 over HTTP, replies read either as one JSON body
or as a Server-Sent Events stream, the `Mcp-Session-Id` header, and the handshake. That taught the
protocol and gave full control of the details CLAUDE.md lists as learned the hard way.

Python has the official SDK, `mcp` (2.3.0 at the time of writing), maintained with the protocol
itself. It is async only (decision 0008 made the agent async partly for this reason).

## Decision

**The agent uses the official SDK**, through a thin module of its own (`quantic_agent/quantic.py`)
that adds what the agent needs on top:

- an anonymous connection (decision 0006), and the `initialize` handshake directly
  (`mode="legacy"`): Quantic speaks the handshake-era protocol, and the SDK's default first probes
  with a newer `server/discover` request, which costs a request per session against Quantic's
  60-a-minute anonymous limit;
- one `Result` (the joined text blocks, and `is_error`) instead of the SDK's content-block types;
- failures sorted into the kinds the research loop acts on: `RPCError` (a JSON-RPC error, the
  request's fault, shown to the model), `ToolServerUnavailableError` (by the same rule as the model
  server's, `network.unreachable`), and `ToolServerError` for the rest.

## Consequences

- No protocol code to maintain: JSON-RPC framing, SSE parsing, sessions and protocol-version
  negotiation are the SDK's. A new protocol revision is a version bump.
- The dependency is large: the lockfile went from 21 packages to 43, including the SDK's server
  side (Starlette, uvicorn) and its own HTTP library, `httpx2`, separate from the `httpx` the model
  client uses. `httpx2` is declared directly, because the network rule imports its exception
  classes.
- The SDK runs its transport in anyio task groups, so a connection that fails arrives as an
  `ExceptionGroup` around the real error. `quantic.py` flattens groups before classifying. A
  cancellation is not wrapped: `asyncio.timeout` around a tool call raises `TimeoutError` (tested).
- What the Go version did by hand and the SDK now hides (SSE as one reply, JSON inside a string) is
  still described in the lesson, since it's what the wire carries.
- The fake server in the tests speaks enough Streamable HTTP for the real SDK, replaying replies
  captured from quantic.finance, so the tests exercise the SDK rather than a stand-in for it.
