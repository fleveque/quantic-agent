# Lesson 05 — The first real tool

**Milestone 5** — the agent asks a real question with real data: the local model is offered
Quantic's `dividend_calendar`, asks for it, and answers from what Quantic returns. In Go this
milestone was mostly protocol: a hand-written MCP client, JSON-RPC, Server-Sent Events. Here the
official SDK does that, so the work moved: to the boundaries the SDK doesn't cover, and to what it
costs.

*Also readable as a [formatted page](https://claude.ai/artifact/T5ixXHQr63Bx6Nuzwj1GJj), with a [code walkthrough](https://claude.ai/artifact/JAHtPs3kXL3WZhwe4x1eiz) of every file the
milestone added or changed.*

---

## What landed

```
$ uv run quantic-agent --research "Which companies go ex-dividend in the next 10 days?"
tool dividend_calendar {"days": 10} → 810 bytes (309ms)
Based on the data, here are the companies scheduled to go ex-dividend in the next 10 days
(counting from today, October 7, 2026):

*   **Microsoft (MSFT)**: Ex-dividend date of October 8, 2026
*   **Johnson & Johnson (JNJ)**: Ex-dividend date of October 8, 2026
*   **Apple Inc. (AAPL)**: Ex-dividend date of October 9, 2026
*   **Iberdrola (IBE.MC)**: Ex-dividend date of October 10, 2026
...
```

The trace line is on stderr, printed as the call completes: what the model asked for, how much came
back, how long it took. Under it:

```
quantic_agent/llm.py       chat(): /api/chat, with tools and tool calls
quantic_agent/quantic.py   the MCP server, through the official SDK
quantic_agent/tools.py     Tool: a name, a description, an arguments model
quantic_agent/agent.py     Researcher: the seed of the research loop
quantic_agent/network.py   "is the server simply not there?", shared by both clients
quantic_agent/evaltools.py quantic-evaltools: how reliably models call tools
```

## The SDK, and what it hides

You chose the official SDK over a hand-written client ([decision 0009](../decisions/0009-official-mcp-sdk.md)).
Go's milestone 5 lesson was largely about the protocol the SDK now speaks for me:

- MCP is JSON-RPC 2.0 sent over HTTP. Each request is a POST, and the reply comes back either as a
  JSON body or as a short Server-Sent Events stream carrying the same message, whichever the server
  chooses. Quantic answers `initialize` as SSE and `tools/list` as JSON.
- A session starts with `initialize`, whose reply carries an `Mcp-Session-Id` header that later
  requests send back.

None of that appears in this repository's code. One part survives: a tool's output is a JSON
document *inside* the reply's text, so it's decoded twice, once by the SDK (the JSON-RPC message) and
once by whoever reads the calendar:

```python
result = await server.call_tool("dividend_calendar", {"days": 10})
calendar = json.loads(result.text)
```

## What the SDK costs

```
$ grep -c '^\[\[package\]\]' uv.lock     # before, after
21
43
```

Twenty-two more packages. Some are the SDK's own server side (Starlette, uvicorn), which a client
doesn't use but installs anyway. And one is a surprise: the SDK's HTTP library is **`httpx2`**, a
separate package from the `httpx` the model client uses, with its own exception classes. So
milestone 3's "is the server simply not there?" rule had to learn a second `RemoteProtocolError`.
It moved into a module of its own, `network.py`, used by both clients, as Go's `netx` package was.
The operating-system errors underneath are the same, which is why walking the cause chain was the
right design.

Then there's how the SDK fails. It runs its transport in anyio task groups, so a refused connection
doesn't arrive as an exception but as a group of them:

```
builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  httpx2.ConnectError: All connection attempts failed
    httpcore2.ConnectError: All connection attempts failed
      builtins.OSError: All connection attempts failed
        builtins.ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 1)
```

An `ExceptionGroup` (Python 3.11) holds several exceptions raised together, as concurrent tasks can.
`except` matches the group, not what's inside; Python added `except*` to match inside groups. I
didn't use it. `except*` splits a group by type and runs a clause per type, and the question here is
"is *any* leaf the server not being there?". So `quantic.py` flattens the group and asks
`network.unreachable` about each leaf. Without the flattening, the failure isn't recognised and the
command exits 1 instead of 3:

```
FAILED tests/test_cli.py::test_research_without_quantic_exits_3 - assert 1 == 3
```

A cancellation is not wrapped, which matters for milestone 4's deadlines. A test checks that
`asyncio.timeout` around a hanging tool call still raises `TimeoutError`.

## A request I didn't send

The fake MCP server in the tests replays replies captured from quantic.finance, rewriting each
JSON-RPC id to match the request. Its first test checked that the handshake comes first, and failed:

```
E       At index 0 diff: 'server/discover' != 'initialize'
```

The SDK's default mode, `"auto"`, opens with `server/discover`, a request from a newer protocol
revision, and falls back to `initialize` when the server doesn't know it. Quantic doesn't, so that's
one wasted request per session against an anonymous limit of 60 a minute. `mode="legacy"` goes
straight to the handshake Quantic speaks. A library's defaults are a choice someone else made for
someone else's server.

## The arguments model is the schema

Go derived each tool's JSON Schema from a struct by reflection, with `json`, `desc`, `min` and `max`
tags. In Python, Pydantic does it from the model:

```python
class DividendCalendarArgs(ToolArgs):
    days: int = Field(
        default=45,
        le=120,
        description=(
            "How many days ahead to look, counting from today. Defaults to 45; at most 120."
        ),
    )
```

`model_json_schema()` produces what the model is shown, and `model_validate()` checks what the model
sends against the same class, so the two can't disagree. `ToolArgs` makes every tool strict:
`extra="forbid"` refuses an argument the tool doesn't take, and `strict=True` refuses `"10"` for
`10` instead of converting it quietly.

Getting there took one wrong turn. Go left `days` out when the model did, and the server applied its
own default. The obvious Python version is `int | None = None`, and its schema wraps the field in
`anyOf: [integer, null]`, noise for a small model. Pydantic's `SkipJsonSchema[None]` hides the
`null`, but with the bound on the whole field, the schema came out as:

```
"days": {"default": null, "description": "...", "le": 120, "title": "Days", "type": "integer"}
```

`le` isn't JSON Schema; `maximum` is. And `{"days": null}` from a model didn't produce a validation
error, it crashed:

```
TypeError: Unable to apply constraint 'le' to supplied value None
```

So `days` is a plain `int` with the server's own default, 45. The schema is clean
(`"maximum": 120, "default": 45`), and every mistake is one readable line. The difference from Go:
the agent always sends `days`, so the recorded call says which window was asked for.

The errors are written for the model, because that's who reads them:

```
dividend_calendar arguments: days: Input should be less than or equal to 120
dividend_calendar arguments: nights: Extra inputs are not permitted
```

A test compares our schema's argument names and types with the schema the server publishes, so the
two can't drift apart unnoticed. And the description is the agent's own. The server's still ends
"buy before the ex-date to receive the next dividend", and the agent is informational, never
advisory (design N5). A test checks ours never says "buy".

## Protocols are Go's interfaces

Go's research loop declared what it needed from a model and a tool server as interfaces, in the
package that used them:

```go
type ToolServer interface {
	CallTool(ctx context.Context, name string, arguments any) (mcp.Result, error)
}
```

Python's equivalent is `typing.Protocol`:

```python
class ToolServer(Protocol):
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> quantic.Result: ...
```

Like a Go interface, it's satisfied by any class with matching methods, without naming it. The
tests' fakes are small dataclasses with a `chat` or `call_tool` method; neither mentions `Model` or
`ToolServer`.

Go also kept two lines asserting at compile time that the real clients satisfy the interfaces. The
Python version is an assignment only pyright reads:

```python
if TYPE_CHECKING:
    _model: type[Model] = llm.Client
    _server: type[ToolServer] = quantic.Server
```

`TYPE_CHECKING` is `False` when the program runs, so these lines never execute. Changing
`call_tool`'s `arguments` to a `list` to check it works:

```
error: Type "type[Server]" is not assignable to declared type "type[ToolServer]"
    "Server" is incompatible with protocol "ToolServer"
      "call_tool" is an incompatible type
          Parameter 2: type "dict[str, Any]" is incompatible with type "list[Any]"
```

## The loop, and calls recorded as they happen

`Researcher.ask` is milestone 5's research loop. The model is offered the allowlisted tools. Every
mistake the model can fix (an unknown tool, arguments that don't validate, a tool's refusal, a
request the server rejects) goes back to it as the tool's result, and counts against a cap of four
calls. A failure it can't fix, such as Quantic being down, stops the loop.

Go returned the calls made so far *together with* the error, `(Answer, error)`, so the command could
print them even on failure. Python has no second return value for an exception to ride along with.
Instead, `ask` takes a callback, `on_call`, called with each call as it completes. The command
passes one that prints the trace line, so the trace appears live, and a failure loses nothing that
was already printed. Milestone 7 will pass one that writes the call to SQLite: Go's design said tool
calls are recorded as they happen, so a stopped run keeps its audit trail, and this is that hook.

## The evaluation, and files that ship inside the package

`quantic-evaltools` puts each model through eight questions whose right first move is known, and
judges only the first reply. Go compiled its cases into the binary with `//go:embed cases.json`.
Python's version is a file in the package, read with `importlib.resources`:

```python
files("quantic_agent").joinpath("eval_cases.json").read_bytes()
```

That reads it from wherever the package is installed, including from inside a wheel. A check of the
built wheel confirmed the JSON is in it. One run against the real model:

```
$ uv run quantic-evaltools --models qwen3.5:9b --repeat 1
CASE                 qwen3.5:9b
explicit window      1/1
this week            1/1
two months           1/1
beyond the maximum   0/1
...
TOTAL                7/8 (88%)

qwen3.5:9b · beyond the maximum · dividend_calendar arguments: days: Input should be less than or
equal to 120 · dividend_calendar {"days":180}
```

The same failure Go measured: asked about six months, the model asks for 180 days from a tool that
covers 120, whatever the schema says. That's why the bound is enforced, not just described.

## What changed from the Go version

- **No hand-written protocol**: the SDK, behind `quantic.py`.
- **`mode="legacy"`**, found by a test, to skip a request Quantic doesn't understand.
- **Exception groups**, flattened before classifying.
- **`days` is always sent**, defaulting to 45, where Go left it out.
- **`on_call`** instead of returning calls alongside an error.
- **No `QUANTIC_MCP_TOKEN`.** Go accepted a token for authenticated tools. Nothing needs one yet, and
  decision 0006 says a service token, not a personal one, comes when something does.

## What I'm taking into milestone 6

- A library's defaults suit someone's server. Test what the wire actually carries.
- Concurrency libraries raise groups; flatten them where the question is "any of these?".
- The arguments model is the schema. Check both what it shows and what it refuses.
- Protocols are interfaces declared by the consumer; pyright checks the real classes against them.
- The answer the model wrote is now worth checking. Milestone 6 is the provenance validator: every
  figure in that answer has to come from what the tools returned.

---

**Previous:** [Lesson 04 — Async, deadlines and letting go](04-async-deadlines-and-letting-go.md)
