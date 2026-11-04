# Posted texts as examples, measured — 2026-11-04

Milestone 19 ([decision 0022](../../decisions/0022-posted-examples-for-the-writer.md)). Every
company the daily runs 8–13 wrote about (10 in all; Brown-Forman in four runs), re-written from its
stored facts on its own day by the default model (Qwen3.8-27B `UD-IQ3_S`, `num_ctx` 32768), twice
each: once with no examples (**baseline**), once with `daily.pick_examples` over the five posted
texts there were on 2026-11-04 (**examples**): Realty Income, Amphenol, Entergy and Pfizer ticked as
written, Brown-Forman edited. The database was a copy of the agent's. Each write is a line in
[`runs.jsonl`](runs.jsonl): attempts, seconds, versions ready and held, the first attempt's
problems (its raw reply re-checked with `check_version`), 5-word phrases shared with the examples,
and the texts.

| | Baseline | Examples |
|---|---|---|
| Writes | 20 | 20 |
| Needed a retry | 13 | 12 |
| First-attempt problems | 24 | 24 |
| …of them, a figure not in the data | 6 | 9 |
| Versions ready / held | 60 / 0 | 59 / 5 |
| Seconds per write | 10.6 | 12.4 |
| Writes sharing a 5-word phrase with an example | — | 6 |

## What it shows

- **No measurable change on what the checks see.** Retries, first-attempt problems and figures
  are within a write or two of each other. Per company it went both ways: Hitachi and Entergy needed
  no retry with examples (5 and 2 problems at baseline, 0 with), Realty Income, Amphenol and
  Pfizer had more. The 5 held versions didn't recur: the same four companies re-written twice more
  with examples ([`probe.jsonl`](probe.jsonl), problem texts recorded) held none.
- **The figures weren't copied from the examples.** The probe's four first-attempt figure problems
  were "1.5", "17%", "3.19%" (computed by the writer, as at baseline) and "3%", which the check
  matched in "5.73%", not a copied figure. The checks would have sent a copied one back anyway.
- **Copying is phrasing, not claims.** The shared phrases are "per year over the last five",
  "moved its annual rate from", "has raised its payout for": Entergy's and Amphenol's wording.
  One Hitachi post took Amphenol's "increase seen on Oct 29" shape; Hitachi's own facts had the
  same date, so it passed.
- **The one edit showed, a little.** Nike's posts with examples name "Nike ($NKE)", as four of
  the five posted texts name theirs (baseline wrote "$NKE" alone), and put the price as the cause with "while the
  dividend…", the shape of the Brown-Forman edit. Across the yield posts, 5 of 30 versions stated
  the price cause with examples, 4 of 30 without: one sample's worth.

## What it doesn't show

- **Whether the posts read better.** That's the reason for the feature and no check measures it.
  New wording the checks miss also appeared with examples ("a sharp rise", "the yield spike"),
  which the review's tone rules catch, not code.
- **Four of the five examples are the agent's own drafts**, ticked as written. They teach the
  writer to write like itself; only Brown-Forman carries an edit. The examples get more useful as
  edited posts accumulate, which is also when this should be measured again.
