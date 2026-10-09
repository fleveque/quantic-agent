# Two models on the agent's own work — 2026-10-09

Why the default model changed from `qwen3.5:9b` to Qwen3.8-27B `UD-IQ3_S` (decision 0005, update of
2026-10-09). Both models as published, on the target machine (RTX 4070 Ti Super 16GB, Ollama 0.34.4),
live quantic.finance data, the same day, so both saw the same calendar. The week after Friday
2026-10-09 is 2026-W42: Procter & Gamble and Coca-Cola.

## How it started: the 9B's Week Ahead, 40 runs

Milestone 12's first real runs ([`2026-10-09-pull-request/`](../2026-10-09-pull-request/README.md))
held three of five posts because the prose kept "two". More full runs of the merged code
([`week-ahead-9b.txt`](week-ahead-9b.txt)) found two failures, at different steps:

| | Morning (5) | Second batch (15) | Third batch (20) | All |
|---|---|---|---|---|
| Research stopped after the calendar, no company looked up | 0 | 3 | 2 | 5 of 40 |
| Prose still had a figure after 3 attempts (of runs that wrote) | 3 of 5 | 0 of 12 | 4 of 18 | 7 of 35 |

About one run in three would publish nothing. The third batch moved the question's day count inside
the week's description ("…to Sunday 2026-10-18, 9 days from today: find every company…") so the
question ends on the instruction; 2 of 20 still stopped early, against 3 of 15, so it wasn't
merged. The research failures are the model stopping, not a count it got wrong: each asked for
`{"days": 9}`, exactly right.

## Prompts don't fix "two"

The prose step alone, 20 writings per version from the same data ([`prose.txt`](prose.txt)): the
merged prompt published 19 of 20 for W42 and 20 of 20 for W43 (three companies). A prompt reworded
to never say "two" itself and to name the companies instead of counting them published 18 and 13;
the merged prompt with only a new retry ("Where you counted the companies, name them instead")
published 18 and 15. Telling the model more about counting made it count more ("three companies
going…", "two of these…"), and asking it to name each company made it describe each one, streaks in
words included ("four consecutive raises"). Neither was merged.

The harness wrapped the model so every reply's prose went through `provenance.no_figures`, and called
`weekahead.write` 20 times with rows built by `weekahead.gather` from one live `dividend_calendar`
and `get_stock` per company. Writing alone published 39 of 40 with the merged prompt; inside full
runs the same call held 7 of 35. The calls are the same function with the same rows and options; no
difference between them was found.

## The 27B's Week Ahead, 20 runs

[`week-ahead-27b.txt`](week-ahead-27b.txt), `--model hf.co/unsloth/Qwen3.8-27B-GGUF:UD-IQ3_S`:

| | qwen3.5:9b | Qwen3.8-27B `UD-IQ3_S` |
|---|---|---|
| Runs that published every locale | about 24 of 35 | **20 of 20** |
| Research looked up every company | 35 of 40 | 20 of 20 |
| Prose attempts | most needed 2 or 3 | 13 first time, 6 second, 1 third |
| Translations held | 0 | 0 of 120 |
| Time per run, model loaded | about a minute | 102–174s |
| Memory | 6.6GB, all on the GPU | 14GB, 86% on the GPU |

Reading the 20 English posts: they name the companies where the 9B wrote "one entity… the other",
and most get the growth comparison right, often noticing that Coca-Cola's recent growth (4.2%) is
also slightly below its five-year rate (4.5%). Four sentences are wrong, none with a figure the
checks could see: "just one company going ex-dividend" ("one" isn't recognised as a figure),
"Coca-Cola's recent growth rate has slightly outpaced its longer-term average", "Procter & Gamble's
remains higher", and the watch status put down to slowing growth, when the data's only warning is
liquidity. The 9B's posts from the same day had about five such sentences in 26, mostly the same
"outpaced". 17 of the 27B's 20 say "both", which the prompt forbids and the check allows. Its
Catalan is better than the 9B's and still wrong in places a reader sees: "augmentos", "segureta",
"dividendi", "Mentrestant" for *mentre que*.

## Research

`quantic-evaltools`, 10 cases × 5 runs ([`evaltools.json`](evaltools.json)): the 9B 45 of 50, the
27B 48 of 50. Every miss by either was the "beyond the maximum" case, asking for 180 or 182 days of
a calendar that gives at most 120.

`quantic-agent --research`, milestone 8's three questions, 5 runs each per model, every answer read
([`research.txt`](research.txt)):

| Question | Right answer | qwen3.5:9b | Qwen3.8-27B |
|---|---|---|---|
| Which companies go ex-dividend in the next 10 days? | Apple, Iberdrola, P&G, Coca-Cola, Santander | 3 of 5 right; one said "no companies", one put P&G and Coca-Cola outside the window | 4 of 5 right; one left out Santander, on the tenth day, and said why |
| Is Microsoft going ex-dividend this month? | It went ex-dividend yesterday, 2026-10-08 | 0 of 5 found it: none looked Microsoft up, each said it isn't in the calendar from today | 5 of 5 looked it up and found 2026-10-08; one reasoned "one day before the start of the current month" |
| Which stocks go ex-dividend in the next six months? | The seven in the 120 days the tool covers | 4 of 5 listed all seven; one gave up when 180 days was refused | 5 of 5 listed all seven |
| Passed provenance (exit 0) | | 8 of 15 | 12 of 15 |
| Time per run | | 3–11s | 11–58s |

Of the 27B's three flagged answers, one reasoned out loud with day counts ("Oct: 22 days left, Nov:
30…"), one gave "approximately 4 months" (true, derived, so flagged), and one counted four companies
in a window it had just made shorter.

## What it decided

The 27B is better at every task the agent does, at two to five times the time and most of the card
while it runs. The runbook asked of a new default that it fit entirely on the GPU at a usable speed;
that was written for a model someone waits on, and the agent's work is background work, where the
author chose quality over speed. The run deadline went from 300 to 600 seconds. The 9B stays a flag
away: `--model qwen3.5:9b`.
