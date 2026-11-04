# 0022 — What was posted, shown to the daily writer as examples

**Status:** accepted · **Date:** 2026-11-04 (milestone 19)

## Context

Milestone 18 ([decision 0020](0020-posted-text-captured.md)) keeps what went out on X: the versions
ticked as written, and the posts read from `posted` comments, with the version an edited one
started from. Nothing read them back. The daily writer's only example was the prompt's made-up
Northwind post, so every day it wrote from rules alone. The rules cover what a post may not say,
not how the author wants it to sound. On quantic#542 the author edited Brown-Forman's version 2
before posting it: the unconfirmed "64.1% below its 5-year high" dropped, and the cause the data
states made explicit.

On 2026-11-04 there were five posted texts: Realty Income (ex-dividend), Amphenol and Entergy
(changes) and Pfizer (ex-dividend), ticked; Brown-Forman (yield), edited.

## Decision

The author chose, on 2026-11-04:

1. **Same angle first, then the newest, at most 3, never the company being written**
   (`daily.pick_examples`). No embeddings: with five texts, "the nearest" orders all of them, and
   the angle (a change, an ex-dividend, a yield) shapes a post more than anything else. The
   company's own past post is left out because its old figures could pass today's checks.
2. **An edited post is shown as its draft and what was posted**, so the edit is visible. A post
   posted as written, or written from scratch, is shown alone.
3. **Measured before merging**: see [the benchmark](../benchmarks/2026-11-04-daily-examples/).

The examples go in the writer's first message, before the data, labelled "examples of tone and
structure only; their figures, dates and names belong to those companies and are out of date".
Links are stripped: code adds a post's link. Nothing else changes: `check_version` still traces
every figure to the company's own facts, so a figure copied from an example is sent back like any
other.

Each company's examples are recorded with the run (migration 0011, `post_examples`), text and
draft copied as the writer saw them, so the record stays true if a comment is edited later;
`--run N` lists them (design N3).

## Consequences

- The writer's prompt grows with up to three posts, a few hundred tokens.
- A post the author publishes becomes an example from the next run on. A bad post, posted, is a
  bad example: the examples are as good as what's ticked and commented.
- Examples that are all from one angle at first (two changes, two ex-dividends, one yield) can
  pull every post toward the same shape. The repeat window (decision 0019) keeps companies varied;
  nothing keeps the shape varied but the prompt's "different hooks".
- Not done: embeddings, examples for the Week Ahead, examples chosen by how much the author
  edited them.
