# Retrieval, measured — 2026-10-08

Milestone 10: style memory. Approved answers are embedded; a writer is shown the most similar ones
as examples of the house voice. On the target machine (RTX 4070 Ti Super 16GB, Ollama 0.34.4).

## Which embedding model

[`quantic-evalrecall`](recall.json): 6 real answers from this project's runs, 12 questions labelled
with the answers that would be fair examples for them (8 English, 4 Spanish). A question scores when
its most similar answer is one of its labels. Each model plain, and with the prefixes its
documentation asks for.

| Model | Usage | Dims | English | Spanish | All | ms per text | VRAM |
|---|---|---|---|---|---|---|---|
| `nomic-embed-text` | plain | 768 | 5/8 | 3/4 | 8/12 | 2.8 | 323MB |
| `nomic-embed-text` | `search_query:` / `search_document:` | 768 | 5/8 | 3/4 | 8/12 | 3.0 | |
| `qwen3-embedding:0.6b` | plain | 1024 | 6/8 | 3/4 | 9/12 | 10.0 | 2.4GB |
| `qwen3-embedding:0.6b` | instruction on questions | 1024 | **7/8** | 3/4 | **10/12** | 9.9 | |

`nomic-embed-text`'s usual miss: a question about one company's date ("When is Johnson & Johnson's
next ex-dividend date?") finds the 10-day list rather than the one-company answer. Twelve questions
can't rank close models, but `qwen3-embedding:0.6b` was ahead used either way, and its 2.4GB fits
beside the 9B at 32K (6.6GB). It's the default (`--embed-model`), with its documented instruction on
questions. The labels are my judgement: three of the six answers are the same kind of text (a list
of companies and dates), so a calendar question accepts any of the three.

Run three times, the choices and hit counts were identical; `qwen3-embedding:0.6b`'s scores moved
by up to 0.0012 between runs, and the same question scored 0.560 from `--recall` and 0.558 in a run.

## Search in plain Python

[Brute force over random vectors](cosine.txt), plain Python against numpy. Stored at unit length,
a cosine is one `math.sumprod`: 500 answers take about 10ms, 20,000 about 0.4s. numpy is about a
hundred times faster, and not needed: style memory grows by about one approved answer a week, and a
generation takes 5–30 seconds.

## What style memory does

[A real run](style-memory.txt): two answers approved, then "How many years has Johnson & Johnson
raised its dividend?". The writer was shown the approved Coca-Cola answer (0.558) and wrote the same
answer shape, sentence for sentence, including the approved answer's habit of naming the data field
("indicated by the "streak_years" field"). Every figure traced to Johnson & Johnson's own data.
Style memory imitates: what's approved, quirks included, is what comes back.
