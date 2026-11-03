# Our design vs the usual stack

How quantic-agent compares with the same agent built the way a company would usually build it, from
popular open-source or free tools, without writing anything a library already does. This is a
comparison, not a decision: nothing here changes the project. There is a
[formatted version with a diagram](https://claude.ai/artifact/Qtyoaty5UkrTAReSz6SokV).

Our side is measured at commit `60b1123`. "Usual" is a judgement: no census of company stacks exists,
so the picks come from each project's own documentation, licence and activity on 2026-10-30. The
LangGraph behaviour below was run, with stubs for the model and the pull request. The Ollama requests
were captured from a local fake server. Nothing here was run against a real model, and
the full usual stack was never built.

## Summary

- **The frameworks work in Python and TypeScript.** Python is the safer default for this work; a few
  popular tools exist in only one of the two.
- **A framework replaces about 29% of our code at most.** That is the plumbing: the model client,
  tool definitions, the agent loop, retrieval and evals.
- **39% stays in either design.** Provenance, the wording checks, the Week Ahead and daily logic
  are the product, and no library provides them. The remaining 32% changes shape.
- **The cost moves from code to operations.** 38 packages and one database file become 103 packages
  and up to seven extra services, if Langfuse and Prefect are self-hosted.
- **For a company team, the usual stack is the right call.** For one person on one GPU machine, ours
  fits better, with one gap: it doesn't record each model call.

## Python, TypeScript or something else?

| Project | Job | Python | TypeScript | Licence |
|---|---|---|---|---|
| LangChain | Framework | yes | yes | MIT |
| LangGraph | Orchestration | yes | yes | MIT |
| LangSmith | Tracing, hosted | SDK | SDK | SDKs MIT, service is commercial |
| Langfuse | Tracing, self-hostable | SDK | SDK, and the server | MIT outside `ee/` |
| Arize Phoenix | Tracing, self-hostable | SDK, and the server | SDK | Elastic 2.0, server only |
| OpenTelemetry | Tracing standard | yes | yes | Apache-2.0 |
| MCP official SDKs | Tool protocol | yes | yes | MIT; TypeScript moving to Apache-2.0 |
| Pydantic AI | Framework | yes | no | MIT |
| DeepEval | Evals | yes | no | Apache-2.0 |
| promptfoo | Evals | any, run as a CLI | written in it | MIT |
| Mastra | Framework | no | yes | Apache-2.0 outside `ee/` |
| Vercel AI SDK | Framework | no | yes | Apache-2.0 |
| LlamaIndex | Retrieval | yes | TS repository archived | MIT |

Phoenix's licence means it is free to run but isn't OSI open source: Elastic 2.0 is source-available.
The Python and TypeScript versions of LangChain are separate codebases with their own
version numbers, so the two don't always match.

For our other languages there are third-party ports, not official ones:
[langchaingo](https://github.com/tmc/langchaingo) (Go), [langchainrb](https://github.com/patterns-ai-core/langchainrb)
(Ruby) and [brainlid/langchain](https://github.com/brainlid/langchain) (Elixir). OpenTelemetry has
official libraries for all three, so tracing from Elixir or Ruby needs no Python.

## The usual stack

This is what we'd expect a team to pick for this agent. Prefect, Airflow or a Kubernetes CronJob are
interchangeable for scheduling, and Pydantic AI is the main alternative to LangGraph.

| Concern | Ours | Usual stack | What changes |
|---|---|---|---|
| Model | `llm.py`, httpx and Pydantic | `ChatOllama` from `langchain-ollama` | Another provider is a small change |
| Tools | `tools.py`, Pydantic models | `@tool` with a Pydantic schema | Little: same idea, less code |
| MCP | `quantic.py`, official SDK and our `Pace` | `MCPAdapter` from `langchain[mcp]` | Beta; plan on keeping `Pace` and the 429 retry |
| Agent loop | `agent.py`, by hand | LangGraph `StateGraph` | Loop, parallel tool calls and budgets become graph code |
| Resume | Phases, checkpoints, `--resume N` | LangGraph checkpointer, `thread_id` | Free once state lives in the graph |
| Human review | PR, then `--sync` polls | `interrupt()`, resumed by a webhook or a poll | Needs a process listening for the webhook |
| JSON and retries | Ollama `format`, 3 attempts | `format` or `with_structured_output`, a graph edge | The retry stays ours: it depends on our checks |
| Storage | SQLite, `sqlite3`, Alembic | Postgres, SQLAlchemy, Alembic | Several workers can share it; one more service |
| Style memory | `memory.py`, BLOBs, plain Python | `pgvector`, `OllamaEmbeddings` | Indexed search for large collections; see the trap below |
| Tracing | `tool_calls`, `--run N`, journal | Langfuse, self-hosted | Search, diffing, costs and dashboards in a UI |
| Prompts | Package files, reviewed in PRs | Langfuse prompt management | Change a prompt without deploying |
| Evals | `quantic-evaltools`, `quantic-evalrecall` | DeepEval or promptfoo | Standard reports; both run on Ollama |
| Scheduling | systemd timers | Prefect, self-hosted | A UI for runs; the timers already work |
| GitHub | `github.py`, httpx and PyJWT | PyGithub (`Auth.AppAuth`) | Token handling is no longer ours; LGPL-3.0 |
| Packaging | `uv tool install` | Docker image, Compose or Kubernetes | Same build on every machine |
| Provenance | `provenance.py` | Ours, called from a graph node | Nothing |
| Wording and units | `wording.py`, `daily.py` | Ours, called from a graph node | Nothing |
| GPU sharing | `llm.Client(slots=1)`, `gpu.py` | Ours | Nothing, though a company would usually use hosted capacity |

A company would usually call a hosted model rather than run Ollama, and that is where the framework's
provider swap pays off. We kept Ollama here so the two designs differ only in their structure.

## How much code would go

Rough, by module, from 8,068 lines of `src/quantic_agent/*.py`. Tests (6,979 lines, 334 test
functions) aren't counted.

| Effect | Lines | Share | Modules |
|---|---|---:|---|
| Libraries replace most of it | 2,337 | 29% | `llm`, `tools`, `quantic`, `network`, `agent`, `memory`, `evaltools`, `evalrecall`, `github` |
| Changes shape | 2,595 | 32% | `store`, `cli`, `logs` |
| Stays | 3,129 | 39% | `provenance`, `wording`, `weekahead`, `daily`, `xpost`, `publish`, `corrections`, `gpu`, `bench` |

The first row overstates the saving: tool definitions, `Pace` and the eval cases would survive, and
the graph is new code. `weekahead` and `daily` would be rearranged into graph nodes, but their logic
would stay. `__init__.py` makes up the last 7 lines.

## What it takes to run

| | Ours | Usual stack |
|---|---|---|
| Python packages installed | 38 | 103 |
| Services to run, besides Ollama | 0 | 7: six for Langfuse, plus Prefect |
| Database | One file | Postgres, ClickHouse |
| Backups | Copy `agent.db` | One per data store |

The 103 is what `uv pip compile` resolves for `langchain[mcp]`, `langgraph`,
`langgraph-checkpoint-sqlite`, `langchain-ollama`, `langfuse`, `pydantic` and `pyyaml`, so it leaves
out Prefect and the GitHub and eval libraries. `pydantic-ai-slim[ollama,mcp]` with `pyyaml`
resolves to 52.

Langfuse's Compose file has six services: `langfuse-web`, `langfuse-worker`, `postgres`, `clickhouse`,
`redis` and `minio`. Its own docs describe Compose as suited to local use and testing. Phoenix runs
as one container and uses SQLite by default, which suits a single machine far better.

## The Week Ahead in LangGraph

Our write, check, retry and review loop fits LangGraph well. This sketch ran with stub functions for
the model and the pull request. The human-review step is a pause that survives a restart.

```python
def write(state: State) -> dict:
    attempt = state.get("attempts", 0)
    print(f"write: attempt {attempt + 1}, told {state.get('findings', [])}")
    return {"prose": DRAFTS[attempt], "attempts": attempt + 1}


def check(state: State) -> dict:
    findings = ["figure with no source"] if "%" in state["prose"] else []
    print(f"check: {findings or 'clean'}")
    return {"findings": findings}


def route(state: State) -> str:
    if not state["findings"]:
        return "review"
    return "write" if state["attempts"] < 3 else END


def review(state: State) -> dict:
    print("review: opening the pull request")  # a side effect before interrupt()
    verdict = interrupt({"prose": state["prose"]})
    print(f"review: verdict {verdict}")
    return {"verdict": verdict}


builder = StateGraph(State)
builder.add_node("write", write)
builder.add_node("check", check)
builder.add_node("review", review)
builder.add_edge(START, "write")
builder.add_edge("write", "check")
builder.add_conditional_edges("check", route, ["write", "review", END])
builder.add_edge("review", END)
```

The first process stopped at the review, and a second process picked it up from `runs.db`:

```text
=== process 1
write: attempt 1, told []
check: ['figure with no source']
write: attempt 2, told ['figure with no source']
check: ['figure with no source']
write: attempt 3, told ['figure with no source']
check: clean
review: opening the pull request
next: ('review',) | verdict: None | checkpoints: 8
=== process 2
review: opening the pull request
review: verdict approved
next: () | verdict: approved | checkpoints: 9
```

The retries, the findings sent back to the writer and the resume all worked with very little code.
The `check` function is still ours, and it's the part that matters.

## Traps we found by testing

**A resumed node runs again from its top.** "Opening the pull request" printed twice above, once
per process. LangGraph documents this, but with a real pull request it would be a duplicate, the same
outcome as quantic#494. Moving the side effect into its own node before the review fixed it in
our test: the line printed once.

**`OllamaEmbeddings` can't send `truncate: false`.** We captured its request, and the class has no such
field. Ollama's default is `truncate: true`, so an over-long text is shortened silently. Our
`llm.Client.embed` sends `false` so that this fails loudly instead. Anyone using the class would need
to check input lengths first.

**Tracing conventions are still moving.** OpenTelemetry's GenAI conventions are marked Development in
their [own repository](https://github.com/open-telemetry/semantic-conventions-genai), and Langfuse says
it follows them as they evolve. Span attributes may change.

**The packages move too.** `langchain-mcp-adapters` is now archived and MCP support has moved to
`langchain[mcp]`, which requires 1.4.0 or later and is in beta. The LangSmith SDK repository also moved, with no change to
the package. The MCP change does need a migration, and that is the upgrade work a framework brings.

`ChatOllama` was not a problem. It sent `think: false`, `num_ctx`, `format` and `keep_alive` as
asked, and returned `prompt_eval_count`, so most of our Ollama lessons carry over.

## Where each design wins

**The usual stack is better at:**

- Onboarding: new hires already know it, and job postings ask for it.
- Looking at runs: search, filters, cost and latency dashboards in a browser.
- Changing provider or model family with little code.
- Running on several machines, with Postgres and workers.
- Auth code that other people maintain and patch.

**Ours is better at:**

- Running on one machine: one file, no containers, 38 packages.
- Failing loudly: limits and truncation are explicit, in code we can read.
- Debugging: there are no framework layers between a bug and its cause.
- Staying put: the framework upgrades above don't reach us.
- Auditing: `--run N` re-checks a stored answer against exactly the calls it was given. A checkpoint
  table doesn't replace that, so the usual stack would keep an audit table of its own.

Self-hosted Langfuse and Phoenix both keep data on the machine. LangSmith's hosted service doesn't,
so it would not fit the design's non-negotiables here.

## If we were starting today

For a team: LangGraph, Postgres, Langfuse and DeepEval, plus our provenance and wording checks
as graph nodes. For this project as it stands, rewriting wouldn't pay for itself: we'd keep every
check, add seven services, and spend the effort on code that works today.

The one thing worth taking from the usual stack is per-call tracing: a `model_calls` table in
`agent.db`, optionally sent to Phoenix through OpenTelemetry. That remains the author's decision.

## Sources

Checked on 2026-10-30. Versions and licences come from PyPI, npm and the GitHub API.

- LangGraph: [persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
  [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- LangChain: [ChatOllama](https://reference.langchain.com/python/langchain-ollama/chat_models/ChatOllama),
  [MCP](https://docs.langchain.com/oss/python/langchain/mcp),
  [structured output](https://docs.langchain.com/oss/python/langchain/structured-output),
  [guardrails](https://docs.langchain.com/oss/python/langchain/guardrails),
  [archived MCP adapters](https://github.com/langchain-ai/langchain-mcp-adapters)
- Langfuse: [self-hosting](https://langfuse.com/self-hosting),
  [OpenTelemetry](https://langfuse.com/integrations/native/opentelemetry),
  [overview](https://langfuse.com/docs/observability/overview),
  [licence](https://github.com/langfuse/langfuse/blob/main/LICENSE)
- Phoenix: [self-hosting](https://docs.arize.com/phoenix/self-hosting),
  [licence](https://github.com/Arize-ai/phoenix/blob/main/LICENSE)
- OpenTelemetry: [GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai)
- Pydantic AI: [overview](https://pydantic.dev/docs/ai/overview/)
- Evals: [promptfoo](https://www.promptfoo.dev/docs/intro/),
  [promptfoo with Ollama](https://www.promptfoo.dev/docs/providers/ollama/),
  [DeepEval with Ollama](https://deepeval.com/integrations/models/ollama)
- Others: [Prefect server](https://www.prefect.io/docs/v3/manage/server),
  [PyGithub auth](https://pygithub.readthedocs.io/en/stable/examples/Authentication.html),
  [Ollama embed](https://docs.ollama.com/api/embed)
