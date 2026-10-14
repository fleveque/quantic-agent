# The prose's wording, checked, 2026-10-14

The measurements behind milestone 15's wording check ([decision 0017](../../decisions/0017-wording-checks.md)).
Each is 60 writings of the Week Ahead's English prose (`weekahead.write`, up to 3 attempts) from
run 3's recorded data: ISO week 43, Apple and Iberdrola going ex-dividend, the week's earnings and no
raises or cuts. Qwen3.8-27B `UD-IQ3_S`, `--num-ctx` 32768, on the machine of the
[other benchmarks](../README.md). Before each writing the harness asked `gpu.usage()` and would
have stopped if other programs held more than 4096 MiB. It never had to: the GPU was free.

| Writings | The writer | Attempts 1 / 2 / 3 | Held | Mean time |
|---|---|---|---|---|
| [`baseline.jsonl`](baseline.jsonl) | figures only, as on `main` | 58 / 2 / 0 | 0 | 9.3 s |
| [`checked.jsonl`](checked.jsonl) | plus the first rules | 38 / 18 / 4 | 0 | 13.0 s |
| [`final.jsonl`](final.jsonl) | plus exposure, monitoring, decades | 33 / 23 / 4 | 0 | 13.2 s |

Each line is one writing: its last attempt's two sections, the attempts, the seconds, and what
was still wrong after the last attempt (`figures` in the baseline, `findings` in the others: always
empty).

**What the baseline wrote.** 22 of the 60 had wording the first rules name. Read in context:

- "investors", 9: all addressed to an audience, two as advice ("investors should note the tight
  liquidity warning", "the primary focus for income-oriented investors").
- "both", 12: ten counted the companies ("Both companies maintain long histories"), two were
  "both X and Y" ("is both going ex-dividend and reporting earnings"). The prompt forbids "both"
  in any use, so the rule does too.
- "one" and "single", 6: all counts ("one safe name … and one utility name"; "dominated by a
  single name, Apple", which is false as well).
- "sentiment", 1: "may influence sentiment around these and other large-cap names".
- The advice words carried over from the 9B (buy, attractive, alternative…) matched nothing.

**What the retries wrote instead** (`checked.jsonl`, read in full). The named phrases were gone, and
new ones came: "offering exposure to technology and utilities", "warrants a closer look", "a
dynamic to monitor", "requires monitoring", "for those monitoring this week's ex-dividend dates",
"has grown steadily for over a decade". Across all 120 writings "exposure" appeared 10 times, always
as portfolio talk. The final rules add these. Left alone, after reading every use: "the only
companies going ex-dividend" (13 times, a claim the list is complete, true each time), "the broader
market" (narrative: "the broader market awaits earnings reports"), "draw attention".

**What got past the final rules** (`final.jsonl`). Two at the first attempt: "Readers should note
that Iberdrola…" and "warrants closer attention". Both were added after this run, so the final rules
would send back 2 of these 60, and 26 of the baseline's. Also seen, and not wording a rule can
name: "Each name carries a safe profile" and "These companies maintain positive safety profiles",
with Iberdrola on watch. Those are false claims about the data.

**The recorded prose.** The rules find nothing in runs 2 and 3, the second published as quantic#492.
In run 4 they find "income-focused", "investors" and "sentiment". In milestone 11's post (the 9B)
they find "both" and "one".

The harness, outside the repository: for `i` in `range(60)`, check the GPU, call
`weekahead.write(client, week, data, options=llm.Options(num_ctx=32768))` with `data =
weekahead.gather(week, run.calls)` for run 3, and append a line.
