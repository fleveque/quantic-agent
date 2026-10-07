# Lesson 03 — Exceptions you can tell apart

**Milestone 3** — until now every failure of the model client was one `LLMError`, and the only way
to tell "Ollama is stopped" from "that model isn't pulled" was to read the message. Now they're
different classes, the command exits with status 3 when the server isn't there, and the benchmark
stops when it goes away. In Go this took three shapes of error and two `%w` verbs in one format
string. In Python it took one shape, a class, and one surprise: a guard the Go version needed turned
out to do nothing at all.

*Also readable as a [formatted page](https://claude.ai/artifact/URFbirkFqqQNFbe2xfRqLJ), with a [code walkthrough](https://claude.ai/artifact/KjWES5unohRZjtyiMhxCBE) of every change the
milestone made.*

---

## What landed

```
LLMError                      anything from the model client; raised as itself for a bad reply
├── ServerUnavailableError    nothing answered: refused, reset, dropped, no route
└── APIError                  the server answered and said no (status_code, message)
    └── ModelNotFoundError    ...because it doesn't have the model
```

Against the real setup on the desktop:

```
$ uv run quantic-agent --model no-such-model --ask hi
quantic-agent: no-such-model is not on this server. Pull it with: ollama pull no-such-model
$ echo $?
1
$ uv run quantic-agent --ollama http://127.0.0.1:1 --check
quantic-agent: no model server answering at http://127.0.0.1:1. Is Ollama running?
quantic-agent: GET /api/version: [Errno 111] Connection refused
$ echo $?
3
$ uv run quantic-agent --ollama http://olama.local:11434 --check
quantic-agent: GET /api/version: [Errno -2] Name or service not known
$ echo $?
1
```

Status 3 means nothing was attempted, so a scheduler can run the same command again later (design
§3.6). A typo in the host name is a 1: waiting for it won't help.

## Go had three shapes of error; Python has one

Go's milestone 3 used all three of its ways to make errors distinguishable:

| Go | What it is | Asked with | Python |
|---|---|---|---|
| `ErrUnavailable = errors.New(...)` | A sentinel value | `errors.Is(err, llm.ErrUnavailable)` | `class ServerUnavailableError(LLMError)` |
| `*APIError` with `StatusCode` | A struct type | `errors.As(err, &apiErr)` | `class APIError(LLMError)` with attributes |
| `APIError.Unwrap()` returning `ErrModelNotFound` | A sentinel *inside* a type | `errors.Is` sees through it | `class ModelNotFoundError(APIError)` |

In Python every one of those is a class, and every question is `isinstance`, which `except` asks
for you. The third row is where the difference shows. In Go, "a 404 that means the model is missing"
had to be an `APIError` that *also* unwrapped to a sentinel, so both `errors.As(err, &apiErr)` and
`errors.Is(err, ErrModelNotFound)` would succeed. In Python it's a subclass: a `ModelNotFoundError`
*is* an `APIError`, with its status code, and `except llm.APIError` catches it too.

## Order matters, and pyright checks it

A subclass relationship means order matters wherever classes are tested in turn. The command picks
its message with `match`, the closest thing Python has to Go's `switch` on error kinds:

```python
match err:
    case llm.ServerUnavailableError():
        ...
        return EXIT_UNAVAILABLE
    case llm.ModelNotFoundError():
        _not_pulled(model)
    case llm.APIError(status_code=status) if status >= 500:
        ...
    case _:
        _error(str(err))
```

`case llm.APIError(status_code=status) if status >= 500` is a class pattern: it matches an
`APIError`, binds its `status_code` attribute to `status`, and the guard decides. Go needed
`errors.As` into a variable and then an `if`.

I put a catch-all `case llm.LLMError():` first to see what happens. It would swallow every error
before the specific cases, and strict pyright says so:

```
cli.py:83:14 - error: Pattern will never be matched for subject type "Never" (reportUnnecessaryComparison)
cli.py:87:14 - error: Pattern will never be matched for subject type "Never" (reportUnnecessaryComparison)
cli.py:89:14 - error: Pattern will never be matched for subject type "Never" (reportUnnecessaryComparison)
```

After the first case, pyright knows nothing is left to match. Go's `switch` with `errors.Is` would
have compiled the same mistake without a word.

## Deciding what "unavailable" means, by reproducing it

"The server wasn't there" isn't one exception. I made each failure happen and printed what httpx
raised and what it was raised from:

| Failure | httpx raises | Its cause, from the system | Unavailable? |
|---|---|---|---|
| Nothing listening (port 1) | `ConnectError` | `ConnectionRefusedError`, errno 111 | yes |
| Connection reset | `ReadError` | `ConnectionResetError`, errno 104 | yes |
| No route (an IPv6 address on a machine without IPv6) | `ConnectError` | `OSError`, errno 101 | yes |
| Accepted, then closed with no reply | `RemoteProtocolError` | none | yes |
| Unknown host | `ConnectError` | `socket.gaierror`, errno -2 | **no** |
| Unroutable address, 1s timeout | `ConnectTimeout` | `TimeoutError` | **no** |

The trap is in rows one and five: **a refused connection and a DNS failure are the same httpx
class.** Catching `httpx.ConnectError` would treat a typo in `OLLAMA_HOST` as a stopped server, and
a scheduler would retry it forever. Only the cause tells them apart.

Python names the common system errors. `ConnectionRefusedError` and `ConnectionResetError` are
subclasses of `OSError` that Python picks from the errno for you. Go compared against
`syscall.ECONNREFUSED`. Errors without a class of their own, such as "network unreachable", keep their
number in `.errno`, compared with the `errno` module's names.

A timeout stays out on purpose: a slow server isn't a missing one, and milestone 4 is about time.

## The cause chain is Go's second `%w`

Go wrapped both the sentinel and the network error in one message,
`fmt.Errorf("...: %w: %w", ErrUnavailable, err)`, so `errors.Is` could find either. Python does it
with two things that already exist:

```python
except httpx.HTTPError as err:
    kind = ServerUnavailableError if _unreachable(err) else LLMError
    raise kind(f"{method} {path}: {err}") from err
```

The class says what kind of failure it is. `from err` stores the httpx exception as `__cause__`, and
httpx raised that one from httpcore's, which was raised from the system's. The test walks the chain:

```python
assert ConnectionRefusedError in causes(err.value)
```

Python also records an implicit link, `__context__`: the exception that was being handled when a new
one was raised. `raise ... from` sets the explicit one, and a traceback prints both, as "The above
exception was the direct cause of the following exception".

## The guard that did nothing

Go's classifier started by ruling out DNS errors, because a `*net.DNSError` can wrap other errors and
the rule shouldn't depend on what it happens to wrap. I ported that as the first line:

```python
if any(isinstance(c, socket.gaierror) for c in causes):
    return False
```

Then I removed it to check that a test caught its absence. None did. All 66 passed, including the
one that asserts an unknown host is *not* unavailable. A `gaierror` carries the resolver's own codes
(-2, "Name or service not known"), never a connection errno, so nothing further down could match it
anyway. In Go the guard protected against a real overlap. Here the overlap doesn't exist, so the line
is gone, and the docstring says why a DNS failure falls through.

This is the reason for breaking every guarantee on purpose. A line that no test misses is either
untested or unnecessary, and this time it was the second.

## A loop that stops by itself

The benchmark measures several models at several context sizes. If Ollama goes away halfway, every
later request fails the same way, so it should stop and report what it has. Go needed a labelled
`break models` out of two nested loops. In Python an exception crosses every loop on its way up, so
the question is only where to catch it, and how not to lose the results already made:

```python
def _measure_model(client, sizes, predict) -> Iterator[Result]:
    ...
    for ctx in sizes:
        try:
            result = _measure(client, ctx, predict, warm.load_duration)
        except llm.ServerUnavailableError:
            raise
        except llm.LLMError as err:
            print(f"quantic-bench: {client.model} at {ctx}: {err}", file=sys.stderr)
            continue
        yield result
```

It's a **generator**: `yield` hands each result to the caller as it's made, and the function carries
on when asked for the next one. When `ServerUnavailableError` escapes it, the caller already holds
every result yielded before. A function that built a list and returned it would have lost them with
its local variable.

`except ServerUnavailableError: raise` before `except LLMError` is the same ordering rule as `match`:
the subclass first, or the general clause catches it.

## Matching the server's words, once

The command decides by class, never by message. The client can't avoid reading one message, though:
a missing model and a missing endpoint are both 404s, and the only difference is Ollama's JSON body,
`{"error":"model 'x' not found"}`, against its router's plain text. So `_api_error` checks for
`"not found"` in Ollama's own error field, in one place, and turns it into a class. Everything after
that asks the class.

## The address nothing listens on

The tests' dead server was a port bound and closed again. Go's milestone 3 found that flaky under
`-count=1000`: another test binary running in parallel could be given that port a moment later. I
haven't seen it here, since pytest runs tests one at a time, but any other process on the machine can
take a freed port, so the dead address is now `127.0.0.1:1`, a privileged port no server gets by
accident.

The fake server learned two ways to fail. `Reply(drop=True)` returns without answering, so the
standard library closes the connection. `Reply(reset=True)` sets `SO_LINGER` to zero before closing,
which makes the system send a TCP reset instead of a clean close: `ConnectionResetError` on the
client. And a path can answer a list of replies in turn, which is how the benchmark test lets two
requests succeed and drops the third.

## What changed from the Go version

- **No typed-nil trap.** Go's lesson spent a section on a function returning a nil `*APIError` as an
  `error`, which is not equal to `nil`. Python has one `None`.
- **No DNS guard**, as above.
- **Names end in `Error`**, as PEP 8 asks of exception classes, so the sentinel `ErrUnavailable`
  became `ServerUnavailableError`.
- **A reset connection has a test.** Go listed it in the classifier but tested only refused and
  dropped. "No route" is still untested: whether it happens depends on the machine's network.

## What I'm taking into milestone 4

- A kind of failure is a class. Subclass where one kind is a special case of another.
- Order `except` clauses and `match` cases from specific to general; strict pyright flags a case that
  can't be reached.
- `raise ... from err` keeps the cause; the chain is the second `%w`.
- Decide what a failure means by reproducing it, and check each guard by removing it.
- A generator keeps what it has already produced when something goes wrong partway through.
- Timeouts were left out on purpose. They're next.

---

**Previous:** [Lesson 02 — Pydantic models and one HTTP call](02-pydantic-models-and-one-http-call.md)
