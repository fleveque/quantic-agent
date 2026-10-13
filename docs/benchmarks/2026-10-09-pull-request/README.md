# The first pull request, and a Friday — 2026-10-09

Milestone 12: the first real `quantic-agent --pr` against `fleveque/quantic`, as the GitHub App
`quantic-agent-fleveque`, from a Week Ahead written on the target machine (RTX 4070 Ti Super 16GB,
Ollama 0.34.4), `qwen3.5:9b`, live quantic.finance data. The week after Friday 2026-10-09 is
2026-W42 again, with the same two companies as [yesterday's runs](../2026-10-08-week-ahead/README.md)
and the same data, field for field.

## Research: told the date, the model still counted wrong

The first run of the day, with milestone 11's question ("Today is Friday 2026-10-09 … the week from
Monday 2026-10-12 to Sunday 2026-10-18"), asked `dividend_calendar` for 7 days. The calendar counts
from today, so from a Friday 7 days end on the Friday before the week's Sunday; `weekahead.gather`
refused the run ("no dividend_calendar call covers the week"). `--resume` replayed the same calls
and stopped in the same place: the model's answer doesn't change by asking again. Milestone 11's 20
runs of 20 were all on a Thursday, where the 10 days needed are further from a habitual 7.

The question now also says how far away the Sunday is ("Sunday 2026-10-18 is 9 days from today").
Five runs with it, the same Friday: 5 of 5 asked for `{"days": 9}` and gathered the whole week.

## Prose: "two", three runs of five

The same five runs, each to the end:

| Run | Exit | Result |
|---|---|---|
| 1 | 6 | published; Italian held, its summary 4.08 times as long as the English |
| 2 | 4 | nothing written: 'two' in the prose after 3 attempts |
| 3 | 0 | published, all seven locales |
| 4 | 4 | nothing written: 'two' after 3 attempts |
| 5 | 4 | nothing written: 'two' after 3 attempts |

Each held run's last attempt counted the companies ("these two market leaders", "two consumer
defensive giants", "two established consumer staples leaders"), though the prompt forbids it by name.
Yesterday the same prompt on the same data published within 3 attempts 19 times of 20, and in 10
full runs of 10. Nothing found yet explains the difference; the writer isn't shown the question, so
today's change to it doesn't reach it. The prompt itself says "two" twice ("Write two fields", "two
or three sentences"). Later the same day, 35 more runs and two reworded prompts: the
[model comparison](../2026-10-09-models/README.md), which made Qwen3.8-27B the default.

## The pull request

Run 3 became [fleveque/quantic#487](https://github.com/fleveque/quantic/pull/487): author
`app/quantic-agent-fleveque`, one commit by `quantic-agent-fleveque[bot]` on
`agent/week-ahead-2026-W42-run-3`, seven files under `priv/insights/week-ahead-2026-W42/`, and
`main` where it was, at quantic#486's merge commit `174bc21`.

Its English prose has what the checks can't see: "recent earnings acceleration … outpaces the
broader long-term trend", where Procter & Gamble's recent dividend growth (4.0%) is below its
five-year rate (6.0%), and they are dividends, not earnings. The Catalan has "Aquesta set",
"aumentos" and "racha". The pull request is for closing.

## GitHub, live

- Asked, as the App's installation, to create `refs/heads/main`, GitHub answered
  `422 Reference already exists` and `main` didn't move: the rule the client is built on
  (`tests/fixtures/github/ref-exists.json`).
- A JWT signed with a key GitHub doesn't know: `401 A JSON web token could not be decoded`
  (`wrong-key.json`); a string that isn't a JWT: `401 Bad credentials`.
- The installation and its token carry exactly the permissions the App was given: `contents:
  write`, `metadata: read`, `pull_requests: write` (`installation.json`, `access-token.json`, the
  token replaced).
- The deploy after the author merged quantic#486 skipped "Refuse a push to main by a bot" and
  deployed: a person's merge isn't refused.
