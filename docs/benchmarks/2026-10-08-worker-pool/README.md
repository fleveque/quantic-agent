# The worker pool, measured — 2026-10-08

Milestone 9: tool calls from one model reply run at once, runs given together (`--research` several
times) take turns at the GPU, and every MCP request is paced under Quantic's limit. Real runs of
`quantic-agent`, `qwen3.5:9b`, live data from quantic.finance, on the target machine (RTX 4070 Ti
Super 16GB, Ollama 0.34.4).

## The context window

[The same question at 4096 and 32768 tokens](context-window.txt), with Ollama's own log:
"Compare the dividend safety and growth streaks of the companies that go ex-dividend in the next 14
days." Both runs called the calendar, then `get_stock` for nine companies in one reply, run in
parallel (125–143ms each).

| `num_ctx` | Outcome | Tokens recorded | Wall |
|---|---|---|---|
| 4096 (Ollama's default) | unverified, 18 figures with no source | 9,595 | 25.7s |
| 32768 | answered, every figure traced | 18,083 | 29.2s |

At 4096, research's third turn filled the window (`truncated = 1` at 4,095 tokens), and the writer's
prompt was cut to 2,050 of 6,945 tokens: `truncating input prompt limit=2050 prompt=6945 keep=4`.
Keeping 4 tokens means the system prompt's start survived and the question and most of the data
didn't. Nothing in Ollama's reply says so: the recorded tokens are simply lower, because Ollama
counts what it kept. The writer then invented 18 figures, prices among them. 32K held both phases
with room to spare and kept the model wholly on the GPU ([2026-09-24](../2026-09-24-bench.json):
6.6GB at 32K), so it's the default (`--num-ctx`, `QUANTIC_NUM_CTX`).

## What a shared GPU costs

[Three questions, one command each, against one command for all three](batch.txt), twice:

| | Round 1 | Round 2 |
|---|---|---|
| One after another | 14.4s | 14.8s |
| One batch | 10.4s | 10.5s |

The batch takes about 28% less, though its model calls still take turns. Starting a command costs
0.55s, almost all imports (the MCP SDK alone 0.26s), so one process instead of three saves about 1.1s.
The other 3s or so is overlap: while one run's model call holds the GPU, another opens its MCP session
and makes its tool calls. Model time itself doesn't shrink; one GPU does one thing at a time.

## Tool choice with two tools

[`quantic-evaltools`](../2026-10-08-toolcalls-get-stock.json), `qwen3.5:9b`, the 8 earlier cases and
two for `get_stock`, 5 runs each, both tools offered: **45/50**. "Compare the dividend safety of
Microsoft and Johnson & Johnson" asked for both companies in its first reply all five times, which is
what lets their calls run at once. "When does Apple next go ex-dividend?" accepts either tool. The
five misses are the old one: "the next six months" asks for 180 days, over the calendar's 120, and the
arguments check refuses it.

## Not measured

The pace (at most 50 requests in any 60 seconds) never had to wait in these runs: a 14-day question
makes about 15 requests, five of them the session's own. It's tested with short windows. The Week
Ahead, 20–40 companies, is where it will.
