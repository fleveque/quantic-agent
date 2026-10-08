# Lesson 09 — One GPU, many calls

**Milestone 9** — the first milestone with no Go version to port, so no answers to compare against,
only the design's sentence: one GPU, many network calls. The agent learns a second tool,
`get_stock`, and with it the shape of the Week Ahead: one calendar, then one call per company. The
calls a model asks for together now run together. Several questions can run at once, taking turns at
the GPU. Every request to Quantic waits its turn under the rate limit instead of running into it. And
the agent finally asks Ollama for a context window big enough to hold what it fetched, after I
watched what happens when it doesn't.

---

## Choosing, for once

Every milestone so far had a Go version to follow, and the questions were how Python differs. This
one had a design paragraph and three open questions, so I chose them myself, from options laid out
with what each would cost
([decision 0011](../decisions/0011-worker-pool.md)): parallel tool calls *and* batches of questions,
a limiter on our side rather than relying on the 429 retry, and an explicit context window, sized by
measuring. The open question from milestone 8, which date the writer is told is "today", I settled
as it was: the agent's local date.

## Measuring before choosing

Before deciding anything I called the real tools:

```
calendar 544 bytes 423 ms
4 stocks in 7 days: ['MSFT', 'JNJ', 'AAPL', 'IBE.MC']
get_stock MSFT 1538 bytes False 128 ms
3 concurrent: [1538, 1515, 1506] 140 ms
```

Three `get_stock` calls at once took barely longer than one, so the round trip, not Quantic, is the
cost. And 1.5KB is about 500 tokens: a Week Ahead of 30 companies is 15,000 tokens of data, nearly
four times Ollama's default window.

## Calls that run together

When the model wants several companies, it asks for them in one reply: in the evaluation, "Compare
the dividend safety of Microsoft and Johnson & Johnson" asked for both in its first reply five times
out of five. So the loop runs a reply's calls at once:

```python
async with asyncio.TaskGroup() as group:
    tasks = [group.create_task(one(r)) for r in requests]
done = [t.result() for t in tasks]
```

A `TaskGroup` is structured concurrency: the `async with` doesn't end until every task in it has,
so nothing outlives the block. It's Go's `errgroup` and Elixir's `Task.async_stream` in one. The
bound is a semaphore, four at a time:

```python
async def one(request: llm.FunctionCall) -> tuple[Call, quantic.ToolServerError | None]:
    async with slots:
        return await self._run(request, record)
```

`async_stream` has `max_concurrency:` built in; Go uses a buffered channel or `errgroup.SetLimit`.
Python composes the two pieces.

### When one of them fails

The first version let a failing call raise, as milestone 8's loop did. In a `TaskGroup`, a task that
raises makes the group cancel the others:

```
ExceptionGroup('unhandled errors in a TaskGroup', [ConnectionError('the server went away')])
recorded: []
```

Two calls that were on their way to the server, cancelled, never recorded. For an audit log that's
wrong: the run did make those calls. So each task *returns* its failure beside its call, the group
ends normally, every call is recorded, and then the first failure is raised. The caller also gets
the error itself, not an `ExceptionGroup` around it.

Recording happens as each call completes, so a run's calls are numbered in the order they finished:

```
tool get_stock {"symbol": "JNJ"} → 1514 bytes (129ms)
tool get_stock {"symbol": "MSFT"} → 1538 bytes (135ms)
tool get_stock {"symbol": "AAPL"} → 1506 bytes (137ms)
```

The model, though, is shown the results in the order it asked, which is what its own reply says.

## The GPU's queue

The design says model calls go through "a semaphore of capacity 1 around the model client". That's
almost literally the code:

```python
async with self._gpu:
    return await self._call("POST", "/api/chat", ChatResponse, body)
```

`version()` doesn't take it: asking the server its version costs no GPU time, and a test checks it
doesn't wait behind a generation. Then `--research` can be given several times. Each question is
its own run, in its own task, all sharing the client:

```
$ quantic-agent --research "first?" --research "second?" --research "third?"
```

The fake Ollama counts how many requests it was answering at once. With the semaphore, one; without
it, the test fails with `assert 3 == 1`.

### What a shared GPU costs

The design asked for this measurement: "a good place to learn what a bottleneck actually costs".
Three questions, one command each, then as one batch, twice:

```
round 1 sequential total: 14.4s
round 1 batch: 10.4s exit 0
round 2 sequential total: 14.8s
round 2 batch: 10.5s exit 0
```

About 28% faster, with the model calls still one at a time. Where from? Starting the command costs
0.55s, nearly all imports (the MCP SDK alone takes 0.26s), so one process instead of three saves
about 1.1s. The other 3s are overlap: while one run's model call holds the GPU, another opens its MCP
session and fetches. Model time doesn't shrink. One GPU does one thing at a time; what concurrency
buys is never leaving it waiting on the network.

### A task that never started

A batch records each run inside its own task, as the task's first line, not before creating the
tasks. A task cancelled before it starts never runs a line:

```
run 1 recorded as interrupted
started: [1]
```

Run 2 was cancelled before its first step, so it never got to record itself, and so it can't be left
`running` in the database for ever. Recording all runs up front, then starting the tasks, would have
left exactly that behind a Ctrl-C at the wrong moment.

## Pacing instead of being refused

Milestone 8 retries a 429 after waiting one to two minutes. A Week Ahead would hit the limit
regularly, so now the agent counts its own requests. `quantic.Pace` keeps the times of the last
minute's requests in a `deque` and makes the next one wait while there are 50:

```python
while self._sent and self._sent[0] <= now - self.per:
    self._sent.popleft()
if len(self._sent) < self.limit:
    self._sent.append(now)
    return
```

Quantic counts fixed clock minutes. A sliding window is stricter: if no 60 seconds anywhere hold
more than 50, no clock minute does. It sits in the HTTP transport from milestone 8, so it counts what
Quantic counts, every request: a session alone sends five before any tool is called (the handshake,
its notification, the refused event stream, the tool list, the closing `DELETE`). I found that by
counting, when a test meant to show two sessions sharing a pace passed even with a pace each: one
session already went over its limit of three.

## The context window, finally

Since milestone 2, the client's own docstring has called `num_ctx` "the one that bites". With `get_stock` it
did. The
same question, "Compare the dividend safety and growth streaks of the companies that go ex-dividend
in the next 14 days", at Ollama's default and at 32K, with Ollama's own log:

```
slot      release: id  0 | task 278 | stop processing: n_tokens = 4095, truncated = 1
msg="truncating input prompt" limit=2050 prompt=6945 keep=4 new=2050
```

The writer's prompt was 6,945 tokens; Ollama kept 2,050 of them, starting with the first four. The
system prompt's opening survived, and the question and most of the data didn't. The answer
invented 18 figures and wrote about prices being "hypothetical". At 32K the same question was
answered with every figure traced. And Ollama's reply said nothing about it: the run's recorded
token count was simply lower, 9,595 against 18,083, because Ollama counts what it kept. Only its log
knows. So `--num-ctx` defaults to 32768, which kept the 9B wholly on this 16GB card; detecting a
truncation from the agent is still open.

## A validator gap the second tool opened

`get_stock` returns some figures as keys, `"dividend_by_year": {"2014": 1.12, ...}`, and a real
answer that said "$1.12 in 2014" was flagged for the year. The manifest indexed values only. Now keys
that are numbers or dates count as returned, and year-months like `"from": "2020-10"` count for
their year. Re-checking the stored runs with `--run N` showed the difference without running anything
again: the 7-day answer that had seven findings now traces fully.

What it still reports is right. `cagr_5y` is `0.10230450734403207`; "10.23%" is that figure,
converted. N1 says converted figures don't pass, and they don't.

## What I'm taking into milestone 10

- Measure the tools first. Their sizes decided the context window; their latency, the fan-out.
- A `TaskGroup` cancels the siblings of a task that raises. When the siblings' work matters, return
  failures and raise after.
- A semaphore around the one scarce thing is most of a worker pool.
- Concurrency didn't make the GPU faster; it stopped the GPU waiting for the network.
- Count requests where the server counts them, in the transport.
- A silent truncation is the worst kind. Size the window by measuring, and read the server's log.
- A new tool brings new shapes of data, and the validator has to learn them.

---

**Previous:** [Lesson 08 — A loop that can stop](08-a-loop-that-can-stop.md)
