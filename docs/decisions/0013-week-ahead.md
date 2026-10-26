# 0013 — The Week Ahead: public data, data by code, prose without figures, translations held one by one

**Status:** accepted · **Date:** 2026-10-08

## Context

The [content plan](../content.md) makes the Dividend Week Ahead the first post, in seven locales,
and the [format contract](../rendering.md) fixes its shape: typed data in YAML frontmatter, prose in
the body, and no figures in the prose. The plan's Week Ahead has amounts, yields, declared raises,
cuts and radar movers. Quantic's public tools have less: `dividend_calendar` gives each company's
name, symbol, sector, ex-dividend date and payment frequency; `get_stock` its safety status and
reasons, raise streak, growth rates and history, but not the next dividend's amount or a declared
raise. The radar is a user's private watchlist (N4, [decision 0006](0006-anonymous-mcp-for-public-tools.md)).
Quantic's `/insights` section, where the files will be published, doesn't exist yet.

## Decision

The author chose, from options put to them: build on the public data as it is, and gather it with
the existing agentic loop rather than fixed calls.

1. **The post is built from what the public tools return.** Per company: symbol, name, sector,
   ex-dividend date, payment frequency, safety status and reasons, raise streak, growth over the
   last twelve months and five-year growth rate. Field names are the tools' own. No amounts,
   raises, cuts or radar; [content.md](../content.md#the-dividend-week-ahead-as-built) lists what
   would add them.
2. **Research is the agentic loop**, asked for the week after today and told today's date. Code
   then builds the data block from the recorded results: the latest calendar covering the whole
   week, and a `get_stock` for every company in it, or the run fails in its research phase, to be
   resumed. The data is checked against the tool results (`provenance.check_data`) before anything
   is written. Counts aren't in the data: the template counts the list.
3. **The model writes only prose**, as JSON matching a schema (Ollama's `format`), two sections:
   `summary`, before the registration gate (`fold_after: summary`), and `watch`. Prose with any
   figure, in digits or in words, is sent back with the figures named, up to three attempts; after
   that, nothing is written (exit 4). The writer is shown the data under names with no figures in
   them (`cagr_5y` as `long_term_growth`).
4. **Each locale is translated and checked on its own**: no figures, and every section within 0.75
   to 1.75 times the English length. A translation that fails is held: not written, kept in the
   store with its reasons, and the run exits 6. The others are written.
5. **The files**: `--out/week-ahead-2026-W42/{locale}.md`, the ISO week naming the post. The data
   block is serialised once and written into all seven, every string double-quoted. Each file is
   read back before it is published and must say exactly what was checked. Section headings come
   from the package's locale table, not from the model.
6. **A run is recorded before its files are written**, posts and all, in one transaction. A Week
   Ahead run can't be approved as style memory: its review is the pull request (milestone 12).

## Consequences

- Measured on live data (`docs/benchmarks/2026-10-08-week-ahead/`): with today's date in the
  question, 20 of 20 runs gathered the whole week (without it, 2 of 5 didn't); with the final
  prompt, 10 of 10 published, the prose taking two or three attempts. The 9B counts the companies
  ("two") whatever the prompt says; the retry is what removes it. This is design open question 8,
  answered for this model: it can, with retries.
- The translation checks are structural. 114 real translations passed them, and the Catalan had
  errors any reader would see. Publishing `ca`, `fr`, `de`, `it` and `pt` on machine verification
  (design §3.5) rests on a translation quality this model doesn't have; that is for the author to
  weigh before anything is published.
- Numbers in words are recognised in English only: a translation that writes one in another
  language passes.
- A week with more companies than the call budget can look up fails as incomplete. The live
  universe had two to nine a week; the budget is sixteen calls.
- `/insights` must render this format: the Phoenix side reads `sections`, `fold_after` and `data`,
  formats the ratios, words the safety reasons and counts the list.

## Update, 2026-10-14: the dividend, raises and cuts, and earnings

Quantic added what the public tools were missing (quantic#490, quantic#491): `dividend_calendar`
rows carry the forward annual dividend rate, its currency, the yield (a percentage) and the pay
date; `earnings_calendar` lists earnings reports, with `estimated` for a projected date;
`dividend_changes` lists the raises and cuts Quantic saw, from a log that starts 2026-10-14.
`/insights` renders them, and moved posts to `priv/insights/<ISO year>/week-ahead-W<NN>/`.

The author chose, from options put to them: **code makes the two new calls, not the model.**

1. **Point 1 grows.** Each company also has `dividend_rate` (as returned: the latest declared
   payment annualised, never divided into the coming payment), `currency`, `dividend_yield` and
   `pay_date`. Beside the companies, `earnings` (the post's week only, as Quantic requires) and
   `dividend_changes` (the last seven days, without the tool's `kind`: the page compares the rates).
   Nulls are copied as nulls.
2. **Point 2 has a second step.** The loop still finds the week's ex-dividends. Once they are
   complete, and before the checkpoint, code calls `earnings_calendar` through the week's Sunday (a
   day more, for the server's UTC date) and `dividend_changes` for seven days, records the calls
   with the run's, and builds the data from all of them. A resumed run doesn't repeat a call it has.
   Why: the arguments follow from the week, nothing in research depends on the results, and in
   earnings season the calendar is large: on 2026-10-14, 195 reports in ISO week 44 and 184 in week
   45, about 30 KB for the days a Thursday run asks for, which the loop would read again on every
   turn against a 64,000-token budget and a 32,768-token context. The calls come after research is
   known complete, so a run that goes back to research doesn't replay them to the model.
3. **The yield is the one value code changes**: the calendar's percentage divided by 100, since the
   post's ratios are ratios. `provenance.check_data` is told which fields hold such a ratio and
   finds them as that percentage, divided the same way, so the comparison stays exact.
4. **The writer is shown all of it** and may name a company that raised, cut or reports, with no
   figure; told that an estimated date is a projection, it says the company is expected to report.
   The page has its own headings and tables for both lists.
5. **The files** move to `--out/2026/week-ahead-W43/{locale}.md`, as on Quantic, whose build checks
   the path against `period`. The pull request's branch keeps the period:
   `agent/week-ahead-2026-W43-run-N`.

Consequences of the update:

- Measured on live data ([benchmarks](../benchmarks/2026-10-14-week-ahead-data/README.md)): 3 of 3
  runs published all seven locales, prose in one attempt, 143–156s and about 13,500 tokens each;
  all 21 files pass Quantic's own build checks. The model's research is unchanged: three calls.
- The writer is shown every earnings report in the week, 66 that week and nearly two hundred at the
  season's peak. That is prompt the writer reads once, not a loop's, but it is the next thing to
  measure if `--num-ctx` ever overflows.
- The rate and pay date were null for every company on the first day: Quantic fills them hourly and
  nightly. The first weeks will have few raises or cuts, or none.
- Code's calls aren't the model's, but the audit can't tell them apart: `--run N` lists them with
  the rest, after the model's.

## Update, 2026-10-26: code looks the companies up

The calendar the weeks above were measured on held only Quantic's demo stocks, with ex-dates the
demo invented (quantic#506): two to nine a week. With real dates, 2026-W44 has 31 companies. The
model looked each one up, a `get_stock` of a few thousand tokens that stays in its context: 31 of
them are more calls than research's budget (16) and more tokens than the context (32,768) holds.

The author chose: **code looks the companies up**, as it already did the earnings and the changes.
The model is offered only `dividend_calendar` and asked for one that covers the week; code then
calls `get_stock` for each company in it (`weekahead.look_ups`), and a resumed run skips a company
already looked up. Raising the budget and the context was the alternative: the 27B supports
262,144 tokens, and speed doesn't matter for a weekly job, but 31 raw results in the model's
context to rebuild a table code builds exactly gains nothing.

Consequences:

- A week can be incomplete in two ways only: a calendar too short, or a lookup that failed.
- A dry run of 2026-W44 on 2026-10-26: 31 companies, 202 earnings reports, 79 dividend changes;
  the calendar and 33 code calls; prose in 2 attempts; 2 min 36 s; no truncation in Ollama's log.
  Its prose was right on everything checked but one: it called Royal Bank of Canada's growth
  "slowed sharply" where the data says it fell 43.8% (itself likely wrong: RY is a USD listing of a
  CAD payer).
- Quantic's universe has foreign listings of the same company (Zoetis three times), so the data
  block repeats them.
