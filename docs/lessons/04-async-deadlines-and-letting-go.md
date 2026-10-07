# Lesson 04 — Async, deadlines and letting go

**Milestone 4** — every run gets a deadline, and Ctrl-C or `SIGTERM` cancels the request in flight,
so that stopping the agent gives the shared GPU back at once. In Go that meant a `context.Context`
as every function's first argument. Python has no context. It has two ways to get the same result,
and they lead to different code for every milestone after this one. So this milestone starts with a
decision, and the code follows from it.

*Also readable as a [formatted page](https://claude.ai/artifact/Rrre4qcYJJdAMwTrMw1RLq), with a [code walkthrough](https://claude.ai/artifact/LjytQhW7PHSoTDN8XDn5Ps) of every change the
milestone made.*

---

## The decision: async

Go's context does two jobs: it carries a deadline for a whole run, and cancelling it ends whatever
is waiting on it. In Python:

- **Synchronous code** can be interrupted by Ctrl-C (`KeyboardInterrupt` lands wherever the program
  is), and `SIGTERM` can be made to do the same. But a deadline over a whole run has to be a
  remaining-time budget handed to each request, and httpx's timeouts apply per phase (connect,
  write, each read), so a run can overshoot it.
- **Asynchronous code**, with `asyncio`, has both built in. `asyncio.timeout(300)` bounds any block,
  however many requests it makes. Cancelling a task stops it at the `await` it's waiting on, and httpx
  closes the connection.

Two things later in the roadmap tipped it. The official Python MCP SDK, which milestone 5 may use,
is async only: `ClientSession.initialize` and `call_tool` are coroutines. And milestone 9's
"serialised GPU, parallel I/O" is `asyncio.Semaphore(1)` and a `TaskGroup`. I chose async. It's
[decision 0008](../decisions/0008-async-for-deadlines-and-cancellation.md).

## What async is, coming from Go and Elixir

A goroutine and a BEAM process are both things the runtime can pause anywhere: the scheduler decides.
An asyncio **task** is paused only where its code says `await`. Between two `await`s, nothing else
runs. One thread, one event loop, many tasks taking turns at the `await`s.

```python
async def version(self) -> str:
    return (await self._call("GET", "/api/version", _Version)).version
```

`async def` makes a **coroutine function**: calling it doesn't run it, it returns a coroutine object,
and `await` runs it until it finishes, letting other tasks go whenever it's waiting. `asyncio.run(...)`
starts the loop, runs one coroutine to completion, and closes the loop.

The cost is that async spreads. A plain function can't `await`, so anything that calls the client has
to be `async def` too, and so on up, until the one place that calls `asyncio.run`: each command's
`main`. People call this function colour. Go has no colours: any function can block, and the runtime
handles it. In this codebase async stops at `main`, which still parses arguments synchronously and
then runs one coroutine.

## The client has no timeout of its own

Milestone 2 set 300 seconds on the client because httpx's default, 5 seconds, is a sixth of a cold
model load. That number is gone:

```python
self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=None)
```

How long a call may take is now the caller's decision, as with Go's context:

```python
async with asyncio.timeout(args.timeout or None):
    if args.check:
        return await _check(client, args.ollama)
    return await _ask(client, args.ask)
```

`asyncio.timeout(seconds)` is `context.WithTimeout`. When time runs out, it cancels the task, the
`await` in flight raises `CancelledError`, and as that leaves the `async with` block, `asyncio.timeout`
turns it into `TimeoutError`. One deadline covers `--check`'s two requests together. `None` means no
limit, so `--timeout 0` turns it off.

The default is still five minutes. The slowest request measured on the target machine took 94
seconds, the slowest cold load 31, and the deadline must never be short enough to cut off a load.

## Why a cancellation can't look like a dead server

Milestone 3's client turns every `httpx.HTTPError` into an `LLMError`, and some into
`ServerUnavailableError`. Go had to check `ctx.Err()` first, so that a cancelled request wasn't
reported as an unreachable server. Python needs no check: `CancelledError` derives from
`BaseException`, not `Exception`, so `except httpx.HTTPError` (and `except Exception`) let it through.

Broadening the client's `except` to `BaseException` shows what that protects:

```
E           asyncio.exceptions.CancelledError
E           quantic_agent.llm.LLMError: POST /api/generate:
FAILED tests/test_llm.py::test_a_deadline_ends_the_request - quantic_agent.ll...
```

The deadline ran out, and the caller was told the server had failed.

## What Ollama does when the agent lets go

Go measured this; I measured it again with the async client, since the guarantee depends on httpx
actually closing the connection. A long generation, Ctrl-C after four seconds:

```
start 18:40:59.568
ctrl-c 18:41:03.570
exit: 130 at 18:41:03.595
quantic-agent: stopped; the request in flight was cancelled
```

And Ollama's log, at the same moment:

```
[GIN] 2026/10/07 - 18:41:03 | 500 |  3.877015462s |       127.0.0.1 | POST     "/api/generate"
srv          stop: cancel task, id_task = 3429
slot      release: id  0 | task 3429 | stop processing: n_tokens = 398, truncated = 0
srv  update_slots: all slots are idle
```

The agent was gone 25 milliseconds after the signal, Ollama stopped generating after 398 tokens, and
the GPU read 0% two seconds later. Ctrl-C one second into a cold start:

```
level=WARN msg="client connection closed before llama-server finished loading, aborting load"
[GIN] 2026/10/07 - 18:41:16 | 499 |  961.580724ms |       127.0.0.1 | POST     "/api/generate"
```

The load was abandoned, and nothing stayed in memory. That's the other half of why the deadline is
generous: a timeout during a load wastes the load.

## Signals: one is free, the other takes three lines

Ctrl-C comes for free. `asyncio.run` installs its own `SIGINT` handler: the first Ctrl-C cancels the
main task and, once the task has unwound, `asyncio.run` raises `KeyboardInterrupt`. A second Ctrl-C
while that's happening raises `KeyboardInterrupt` immediately. `main` catches both and exits 130.

`SIGTERM`, which is what systemd sends to stop a service, has no such handling. Its default action
ends the process on the spot, with no cleanup. So the commands install one:

```python
def stop() -> None:
    loop.remove_signal_handler(signal.SIGTERM)
    task.cancel()


loop.add_signal_handler(signal.SIGTERM, stop)
```

The first `SIGTERM` cancels the main task, exactly like Ctrl-C. Removing the handler first puts the
default back, so a second `SIGTERM` ends the process at once. Go did the same with
`context.AfterFunc(ctx, stop)`.

The tests send real signals to the test process while a request hangs:

```python
threading.Timer(0.3, os.kill, (os.getpid(), signum)).start()
assert main(["--ollama", ollama.url, "--ask", "hi"]) == 130
```

Removing the `SIGTERM` handler made a memorable failure: no failed test, no output, just the whole
pytest run killed.

```
pytest exit: 143
```

143 is 128 + 15, the shell's way of saying "killed by signal 15". Without the handler, the default
action took the test runner with it.

## Keeping what the benchmark measured

`quantic-bench` gets a timeout per request (`--timeout`, ten minutes) rather than per run: a request
that runs out of time is reported, and the next size is tried. Ctrl-C stops the whole run, but it
should still print what was measured, as Go's did.

That means catching `CancelledError`, which is usually wrong: a task that swallows its own
cancellation leaves whoever cancelled it waiting for an exit that never comes. At the top of a program
nothing is waiting, so it's the one place it's right, and `uncancel()` records that it was handled:

```python
except asyncio.CancelledError:
    interrupted = True
    if task := asyncio.current_task():
        task.uncancel()
```

The measurement loop is an async generator now (`async def` with `yield`, consumed with `async for`),
so, as in milestone 3, every result yielded before the cancellation is already in the caller's list.
Without the `except`, the test sees nothing printed at all:

```
E           json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
FAILED tests/test_bench.py::test_ctrl_c_stops_the_run_and_keeps_what_was_measured
```

## Testing async code, and a server that waits to be hung up on

pytest runs plain functions. anyio, which httpx is built on, ships a pytest plugin that runs `async def`
tests: `pytestmark = pytest.mark.anyio` at the top of a module, and an `anyio_backend` fixture in
`conftest.py` that says "asyncio".

To test that a cancellation really closes the connection, the fake server needed a reply that never
comes: `Reply(hang=True)`. The handler waits until the client's end of the socket closes, and counts it:

```python
readable, _, _ = select.select([self.connection], [], [], 0.01)
if readable and self.connection.recv(1, socket.MSG_PEEK) == b"":
    fake.hangups += 1
```

A socket that's readable with nothing to read has been closed by the other side. Every deadline and
cancellation test ends with `assert ollama.wait_for_hangups(1)`: the client didn't just give up, it
hung up, which is what tells Ollama to stop. Go's version of this fake hung forever at first, because
Go's server only notices a client leaving once the request body has been read. Python's
`BaseHTTPRequestHandler` reads the body in `do_POST` before answering, so it didn't come up.

Tests that depend on timing can be flaky. I ran the suite 20 times in a row, then 20 more as four
copies in parallel to load the machine: no failures.

## What changed from the Go version

- **No context parameter.** Go passed `ctx` to every function; here the deadline and the cancellation
  belong to the task, and any `await` inside it honours them.
- **Async spreads**, as above. Go's functions have no colour.
- **`--timeout` is in seconds**, a float, where Go took a duration such as `5m`.
- **A second Ctrl-C** raises `KeyboardInterrupt` at once, which still exits 130. Go restored the
  default handling, so its second Ctrl-C killed the process. A second `SIGTERM` behaves as Go's.
- **Still untested**: that the client has no timeout of its own. Removing `timeout=None` would put
  httpx's 5 seconds back, and no test waits that long.

## What I'm taking into milestone 5

- Deadlines with `asyncio.timeout` around the work, not on the client.
- Cancellation is a `BaseException`: `except Exception` won't swallow it, and nothing below the top
  of a program should.
- Async stops at `asyncio.run` in `main`.
- Measure what the server does when the client lets go; don't assume the library hung up.
- Milestone 5 talks to Quantic's MCP server, and the async SDK is now an option rather than a problem.

---

**Previous:** [Lesson 03 — Exceptions you can tell apart](03-exceptions-you-can-tell-apart.md) ·
**Next:** [Lesson 05 — The first real tool](05-the-first-real-tool.md)
