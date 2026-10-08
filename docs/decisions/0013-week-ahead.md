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
