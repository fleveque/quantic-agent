# The Week Ahead with the dividend, raises and cuts, and earnings, 2026-10-14

The first real runs after Quantic's #490 and #491 ([decision 0013's update](../../decisions/0013-week-ahead.md#update-2026-10-14-the-dividend-raises-and-cuts-and-earnings)).
Three `quantic-agent --week-ahead` runs on Wednesday 2026-10-14, for ISO week 43 (Monday 2026-10-19
to Sunday 2026-10-25), against live quantic.finance, with the default model, Qwen3.8-27B `UD-IQ3_S`,
`--num-ctx` 32768. Same machine as the [other benchmarks](../README.md), Ollama 0.34.4.

| Run | Exit | Time | Research | Code's calls | Prose attempts | Locales | Tokens |
|---|---|---|---|---|---|---|---|
| 2 | 0 | 155s | calendar (11 days), get_stock ×2 | earnings_calendar (12 days), dividend_changes (7) | 1 | 7 of 7 | 13,477 |
| 3 | 0 | 156s | the same | the same | 1 | 7 of 7 | 13,674 |
| 4 | 0 | 143s | the same | the same | 1 | 7 of 7 | 13,461 |

[`runs.txt`](runs.txt) is each run's log, [`prose.txt`](prose.txt) its English prose, and
[`post/`](post/en.md) run 2's seven files as written.

**The data.** Apple and Iberdrola go ex-dividend that week. Quantic had each one's yield
(`dividend_calendar`'s 0.32 and 3.15, written 0.0032 and 0.0315) but no forward rate or pay date yet:
#490 fills them hourly for tracked stocks and nightly for the rest, and this was the morning it
deployed. The earnings calendar for twelve days held 89 reports, 66 of them in the week (33
estimated); the post keeps those 66. No raise or cut had been logged yet: the log started that day.

**Quantic's own checks.** Each run's seven files went through Quantic's `Parser`, `Markdown` and
`Post.build` and the cross-locale data rule, from `main` at quantic#491's merge, run by a script
outside the build (`mix run --no-start`): all 21 files pass. The same script refused a copy of run
2's English file with the yield left as a percentage (`dividend_yield: unexpected 3.15`).

**`--run 4`** re-checks the data against the stored results, the yield found as the percentage it
was divided from: "every value in the data traces to a stored tool result".

**The prose, read.** Each sentence was checked against the data.

- Correct: Apple's recent growth below its longer-term rate (3.9% against 4.9% over five years),
  Iberdrola's above (6.2% against 2.9%); Iberdrola reporting in the same week (2026-10-21);
  Netflix, IBM and Tesla reporting (confirmed dates, which "expected to report" also fits);
  Cleveland-Cliffs "expected to report" (an estimated date).
- Not caught by any check, all in run 4: "for income-focused investors" addresses an audience the
  data doesn't name, and "may influence sentiment around the week's ex-dividend dates" is a
  speculation, the kind of sentence the review is for (CLAUDE.md, "Next", item 4).
- Run 2 wrote "No dividend changes are recorded", true but about the data rather than the week.
