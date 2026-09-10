# 0001 — Agentic research, constrained writing

**Status:** accepted · **Date:** 2026-09-10 · **Supersedes:** the fixed-pipeline sketch in the
original design

## Context

The agent must never publish an invented number (design N1). The first design achieved this by making
the pipeline fixed: each task declared its data dependencies up front, the agent fetched them, and the
model only wrote prose over facts it was handed. The model never chose a tool.

Two problems with that.

First, the justification was wrong. The provenance manifest records `{tool, args, response}` for every
call regardless of *who* decided to make it. A model-initiated call is recorded exactly like a
task-initiated one, so the N1 guarantee never depended on the pipeline being fixed. What a fixed
pipeline actually buys is predictable cost and no wandering — real benefits, but much smaller ones
than "this is what makes the invariant hold".

Second, a fixed pipeline teaches almost nothing about LLM engineering. This project's primary purpose
is learning — Go, and how to build with models. A pipeline that never lets the model decide anything
is a template engine with a language model attached.

## Decision

Split the run into two LLM phases with deliberately different freedom.

**Research — a real agentic loop.** The model chooses tools and can follow a thread: *this yield
jumped 40%, so check the payout ratio, then the last five dividends, then whether the price
collapsed.* Every tool in the research allowlist is read-only, so the blast radius is zero.

Bounded per task kind: max tool calls, wall-clock deadline, token budget, tool allowlist, and
short-circuiting of repeated identical calls. A breach is a normal exit, not a failure — the manifest
is whatever was gathered and the validator judges it on merit.

**Writing — no tools at all.** A separate call receives only the manifest and produces prose. It
cannot fetch, so it cannot wander mid-sentence into invention, and it cannot reach for a figure it
never saw.

**Delivery tools stay outside the loop.** `create_pr` and `enqueue_for_review` are reachable only at
the terminal step and never appear in the research allowlist, so no amount of wandering can cause the
agent to publish.

## Consequences

**Good.** The N1 invariant is unchanged — arguably strengthened, since the manifest now records a
genuine research trail rather than a predetermined fetch list. Content quality should improve, because
the model can chase the interesting thread instead of writing over a fixed slab of data. And the Go
surface gets much richer: a dispatch loop, JSON schemas generated from structs by reflection, budget
accounting, retries with backoff on malformed tool calls, and `context` cancellation threaded through
a multi-call loop.

**Costs.** Runs are no longer deterministic — the same trigger can produce different research paths,
which makes reproducing a bad draft harder and makes the tool-call log load-bearing for debugging.
Cost per run becomes variable and needs active budgeting. More sequential model calls per run means
more contention on the single GPU, making the inference semaphore matter more than it did.

**Rejected alternative — fully open loop.** No allowlist, no call cap, budget only. Closest to a real
agent and the most to learn from, but runs spiral and waste GPU hours on nothing. The bounds cost
little and remove the failure mode.

**Rejected alternative — plan-then-execute.** Model emits a plan of intended calls, which is recorded,
then executes against it. More predictable and the plan is a nice auditable artifact, but it's
scaffolding built before the loop it scaffolds is understood. Revisit once the plain loop is working.
