# 0008 — Async: asyncio and httpx.AsyncClient, for deadlines and cancellation

**Status:** accepted · **Date:** 2026-10-07

## Context

Milestone 4 ports the Go version's `context.Context`: every call takes one, it carries a deadline
for the whole run, and Ctrl-C or `SIGTERM` cancels it, which cancels the request in flight. Ollama
then stops working on that request: a cancelled generation frees the GPU within about a second, and a
cancelled load is aborted (design §3.6). The GPU is shared with the author, so stopping the agent
has to give it back at once.

Python has two ways to get there, and every later milestone inherits the choice:

- **Synchronous**, with `httpx.Client`. Ctrl-C raises `KeyboardInterrupt` wherever the program is,
  and `SIGTERM` needs a handler that does the same. A deadline over a run becomes a remaining-time
  budget passed as each request's timeout. But httpx's timeouts apply per phase (connect, write,
  each read), not to a whole request, so a run can overshoot its budget.
- **Asynchronous**, with `asyncio` and `httpx.AsyncClient`. `asyncio.timeout()` is a real deadline
  over any block of code. Cancelling a task delivers `CancelledError` at the `await` in flight, and
  httpx closes the connection. That's Go's context, built into the event loop.

What comes next weighs on it. Milestone 5 talks to Quantic's MCP server, and the official Python MCP
SDK (`mcp` 2.3.0) is async only: `ClientSession.initialize` and `call_tool` are coroutines.
Milestone 9 serialises the GPU and runs network calls in parallel, which is `asyncio.Semaphore(1)`
and a `TaskGroup`.

## Decision

1. **The agent is asynchronous.** The model client is `httpx.AsyncClient` with `async` methods and
   no timeout of its own; callers bound calls with `asyncio.timeout()` and cancel tasks to stop
   them. Commands parse their arguments synchronously, then run one coroutine with `asyncio.run`.
2. **Ctrl-C and `SIGTERM` cancel the main task.** `asyncio.run` does it for Ctrl-C; a loop signal
   handler does it for `SIGTERM`, once, so a second one ends the process. A cancelled run exits
   with 130.
3. **Tests run async code with anyio's pytest plugin** on the asyncio backend. anyio is already
   installed (httpx and the MCP SDK are built on it); it's declared in the dev group because the
   tests use it directly.

## Consequences

- Every function that waits on the network is `async def`, and every caller `await`s it. A
  synchronous function can't call one without starting an event loop, so async spreads upwards to
  each command's entry point and stops there.
- Cancellation is a `BaseException` (`asyncio.CancelledError`), so `except Exception` and the
  client's `except httpx.HTTPError` let it through: a cancelled request is never mistaken for an
  unavailable server. Code that swallows it must call `uncancel()`, and only the top of a program
  should.
- Milestones 5 and 9 can use the MCP SDK and asyncio's primitives directly.
- Measured on the target machine with this client: Ctrl-C during a generation stopped Ollama's work
  (its log: `stop processing: n_tokens = 398`) and the agent exited 25ms later; Ctrl-C during a cold
  load aborted the load (`client connection closed before llama-server finished loading, aborting
  load`).
