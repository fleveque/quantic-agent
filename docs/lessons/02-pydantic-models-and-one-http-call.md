# Lesson 02 — Pydantic models and one HTTP call

**Milestone 2** — the client for the local model server, and the two commands that use it:
`quantic-agent --check` and `--ask`, and `quantic-bench`. In Go this was structs, tags, pointers
and `net/http`. In Python it's Pydantic and httpx, and most of the Go lesson's care turns out to be
unnecessary. Two of the defaults would have broken the client without saying anything, though, and
neither one made a sound until a test compared numbers.

---

## What landed

```
src/quantic_agent/llm.py     Client: generate, version, models, running; LLMError
src/quantic_agent/cli.py     --check, --ask, --ollama, --model
src/quantic_agent/bench.py   quantic-bench: speed and GPU residency per model
tests/conftest.py            a fake Ollama on a real local socket
tests/fixtures/ollama/       replies captured from a real Ollama, from quantic-agent-go
```

Against the real server on the desktop, an RTX 4070 Ti SUPER:

```
$ uv run quantic-agent --check
ollama 0.34.4 at http://localhost:11434
  hf.co/unsloth/Qwen3.8-27B-GGUF:UD-Q3_K_XL  14.1 GB  27.3B  Q3_K_L  ctx 256K  tools thinking completion vision
  hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S  13.0 GB  27.3B  IQ3_S   ctx 256K  tools thinking completion vision
* qwen3.5:9b                   6.6 GB  9.7B   Q4_K_M  ctx 256K  completion vision tools thinking
  ...
$ uv run quantic-agent --ask "Reply with exactly: ok"
ok
qwen3.5:9b · 2 tokens · 14ms
$ uv run quantic-bench --models qwen3.5:9b --contexts 4096,8192 --predict 64
MODEL       CTX  PROMPT tok/s  GEN tok/s  RESIDENT  ON GPU  LOAD  TOTAL
qwen3.5:9b  4K   5273          94.8       5.5 GB    100%    0.0s  1.3s
qwen3.5:9b  8K   5225          93.3       5.7 GB    100%    0.0s  4.8s
```

`quantic-bench` is the second line in `[project.scripts]`, as lesson 01 promised: no new
directory, no second `main` package.

## One model per shape, and no tags

Go needed two structs for one request (what the caller sets, what goes on the wire), and every field
carried a tag, `json:"num_ctx,omitempty"`, because a Go field has to start with a capital letter to
be exported and the JSON keys don't. Python's names are already `snake_case`, the same as Ollama's
keys, so a Pydantic model is just the fields:

```python
class Options(BaseModel):
    num_predict: int | None = None
    num_ctx: int | None = None
    temperature: float | None = None
    seed: int | None = None
```

`model_dump()` turns it into a dict with those names as keys, and `model_validate_json()` reads a
reply into one, checking every type as it goes. There's still a private model for the wire body,
`_GenerateBody`, but the caller never builds it: `generate` takes keyword arguments, so
`client.generate("hi", think=False)` reads like a call, not a struct literal.

## `None` is "not set", so the pointers go

The Go lesson's longest section was why `Temperature` was a `*float64`: zero is a real temperature,
so "unset" needed a third state, a nil pointer, and three helper functions (`Bool`, `Float64`, `Int`)
because Go can't take the address of a literal. Python has the third state built in. `float | None`
is either a number or nothing, and a model dumped with `exclude_none=True` leaves the nothings out:

```python
client.generate("hi", options=llm.Options(temperature=0, seed=0))
# sends "options": {"temperature": 0, "seed": 0}
```

## `exclude_none` is the `omitempty` question again

Go's trap was `omitempty` on `Stream`: `false` is the zero value, so it would be dropped, and Ollama
streams when the key is missing. Pydantic has three ways to leave things out of a dump, and only one
is right here:

| Option | Leaves out | `stream: False` |
|---|---|---|
| `exclude_none=True` | fields that are `None` | sent |
| `exclude_defaults=True` | fields equal to their default | **dropped** (its default is `False`) |
| `exclude_unset=True` | fields nobody assigned | **dropped**, and `think=None` passed explicitly is sent as `null` |

Switching to `exclude_defaults` is a one-word change, and the test that records the request body
catches it:

```
E       KeyError: 'stream'
FAILED tests/test_llm.py::test_generate_decodes_the_reply - KeyError: 'stream'
```

And without any `exclude_`, every `None` is sent as `null`:

```
E       AssertionError: assert 'think' not in {'model': 'm', 'prompt': 'hi', 'stream': False, 'think': None, ...}
```

## What doesn't decode for free

Go decoded Ollama's durations straight into `time.Duration`, because a `Duration` *is* a count of
nanoseconds and so is the wire value. Python's `timedelta` has no such agreement with anybody, and
Pydantic reads an integer `timedelta` as **seconds**:

```python
class R(BaseModel):
    eval_duration: timedelta


print(repr(R.model_validate({"eval_duration": 205098000}).eval_duration))
```

```
datetime.timedelta(days=2373, seconds=70800)
```

0.2 seconds became six and a half years, with no error. A `BeforeValidator` converts the integer
first:

```python
def _from_nanoseconds(value: object) -> object:
    if isinstance(value, int):
        return timedelta(microseconds=value / 1000)
    return value


Nanoseconds = Annotated[timedelta, BeforeValidator(_from_nanoseconds)]
```

Removing it, the tests show what it would have done to the benchmark and the `--ask` line:

```
E       assert 4e-06 == 4000
E         - quantic-9b:latest · 2 tokens · 205ms
E         + quantic-9b:latest · 2 tokens · 205098000000ms
```

Two smaller losses, both silent. `timedelta` stops at microseconds, so the last three digits of a
nanosecond count go. And `created_at` arrives as `2026-09-24T11:07:31.993290938Z`; `datetime` keeps
`11:07:31.993290`. Neither matters for anything the agent measures, but Go kept both.

## Missing keys are errors now; extra keys still aren't

Go filled a missing key with the zero value: a reply without `response` decoded fine, with
`Response == ""`. A Pydantic field without a default is required:

```
ValidationError: 1 validation error for GenerateResponse
response
  Field required [type=missing, input_value={'model': 'm', 'done': True}, input_type=dict]
```

So I chose. `model`, `response` and `done` are required: a reply without them isn't an answer.
Everything else has a default, the way Go would have treated it. Unknown keys, such as the
`context` array of several hundred token ids, are ignored, as in Go.

## One HTTP call, carefully

```python
self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
```

- **httpx times out after 5 seconds by default.** Go's `http.Client` has no timeout unless given one,
  and the Go client set 5 minutes. A cold load of a 9B model takes 25 seconds, and the runbook has
  seen 31, so the default would fail every first request of the day. The client sets 300 seconds
  until milestone 4 gives each call a deadline. No test catches this one: with the line removed, all
  58 still pass, because nothing in them is slow.
- **The client has to be closed.** It holds a pool of connections. Go's `http.Client` is meant to be
  shared and never closed; httpx's is closed with `close()`, or by a `with` block:
  `with llm.Client(url, model) as client:`. The `Client` class defines `__enter__` and `__exit__`,
  which is all a `with` needs.
- **No `defer resp.Body.Close()`.** Without streaming, httpx reads the whole body before returning, and
  the connection goes back to the pool by itself.
- **Errors are chained, not wrapped in a string.** Go built `fmt.Errorf("llm: %s %s: %w", ...)`.
  Here every failure becomes one `LLMError` with a message, and `raise ... from err` keeps the
  original as `__cause__`, so the traceback shows both. One type for now; milestone 3 is about
  telling them apart.

One surprise from pyright: `resp.status_code != httpx.codes.OK` is an error in strict mode,
"Condition will always evaluate to True". `httpx.codes` is an `IntEnum` whose members are defined as
tuples, `OK = 200, "OK"`, and a `__new__` turns them into ints at run time. Pyright reads the
definition, sees a tuple, and concludes an `int` can never equal it. The code says `200`.

## Tests against a real socket

Go's tests started an `httptest.Server` per test. The Python equivalent is a fixture,
`ollama`, in `tests/conftest.py`: a `ThreadingHTTPServer` from the standard library, on port 0
so the operating system picks a free one, serving in a background thread. Each test says what it
answers and reads back what it was sent:

```python
def test_generate_sends_options_whose_value_is_zero(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    with llm.Client(ollama.url, "m") as client:
        client.generate("hi", options=llm.Options(temperature=0, seed=0))

    assert ollama.bodies[0]["options"] == {"temperature": 0, "seed": 0}
```

The fake server records requests instead of asserting inside its handler. An `assert` there fails the
server's thread, not the test: the same reason Go's handler could call `t.Errorf` but not
`t.Fatalf`.

The first version made the suite take **12.3 seconds** for 58 tests. `--durations` showed every
teardown at exactly 0.50s: `serve_forever` checks whether to stop every half second by default, and
`shutdown()` waits for it. Passing `poll_interval=0.01` brought the suite to **0.49 seconds**.

httpx also offers `MockTransport`, which answers requests without any socket. It's faster and
needs no thread, but it would skip what Go's tests exercised: real HTTP encoding, and a URL without a
scheme (`localhost:11434`, as `OLLAMA_HOST` is written) reaching a real server.

The replies the fake serves are the ones quantic-agent-go captured from a real Ollama, copied
unchanged into `tests/fixtures/ollama/`.

## What changed from the Go version

- **One request object fewer.** `generate(prompt, *, think=None, options=None)` instead of a
  `GenerateRequest` struct; `*` makes everything after it keyword-only.
- **`--check` and `--ask` can't be combined.** Go's `switch` silently preferred `-check`. argparse's
  mutually exclusive group makes it a usage error, exit 2.
- **Required reply fields**, as above.
- **The benchmark is a module in the same package.** It imports `short_count` from `cli`, where Go
  had a copy in each `main` package. Its table is padded by hand: Python has no `tabwriter`.
- **Its JSON keys are the Go version's**, and a test compares them with a file in
  `docs/benchmarks/`, so new runs compare with the measurements decision 0005 rests on.

## What I'm taking into milestone 3

- A Pydantic model per shape on the wire. Field names are the JSON keys; `None` is "not set".
- `exclude_none`, never `exclude_defaults`, for request bodies with meaningful falsy values.
- Check how a library decodes each unit before trusting it. Durations and timeouts both had defaults
  that were wrong for this server, and neither raised.
- `with` for anything that holds a connection.
- `raise ... from err`, so the cause survives. Milestone 3 makes the kinds of failure distinct.

---

**Previous:** [Lesson 01 — A command, a module, and pytest](01-a-command-a-module-and-pytest.md)
