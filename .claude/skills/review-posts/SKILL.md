---
name: review-posts
description: Review a daily X posts issue that quantic-agent --daily opened on the Quantic repository, before the author posts any version. Use when asked to review today's posts, the posts issue, or an issue titled "X posts for <day>".
---

# Reviewing a daily X posts issue

`quantic-agent --daily` opens one issue a weekday on the Quantic repository (decision 0019): for up
to three companies, the versions of a post that passed the agent's checks, the facts each was
written from (in a collapsed "What it was written from" block), and the companies looked up and left
out. The checks catch what a rule can name. This review is for what they can't: claims that are
wrong although every figure traces, and data that is wrong although it is Quantic's.

The author posts on X themselves. Never post, and never edit, comment on or close the issue unless
the author asks in this conversation.

## 1. Find and read the issue

```sh
gh issue list -R fleveque/quantic --state open --search "X posts for in:title" --limit 5
gh issue view N -R fleveque/quantic --json title,body,state,url
```

Without a number, take today's (its title has today's date). The body is the record: read every
version and every facts block. Today's date matters: dates in posts are judged against it.

## 2. Check each version against its own facts

Read each claim, not just each figure. The errors the experiment and the first runs found
(docs/benchmarks/2026-10-28-x-posts/), each of which passed the code's checks:

- **Dates and tense**: `seen_on` is when Quantic saw a new rate, not when the company announced or
  changed it ("raised on Oct 16" is wrong). A future date in the past tense ("reported earnings on
  Dec 17"). An estimated date without "estimated".
- **The price**: `last_known_price` is the last price Quantic saw, on `last_known_price_as_of`.
  "trades at", "is now at", "shares are at" present it as current.
- **Causes**: the only cause the data states is `why_the_yield_is_high`, when present. Any other
  cause is made up, including through small words: "as the price is down", "so", "backed by",
  "supports the yield", "reflecting".
- **Field meanings**: `dividend_history_starts` is where Quantic's history begins, not the streak
  ("a streak that started in 2014"). `dividend_growth_per_year_5y_pct` is per year, not in all.
  `streak_years` is years of increases. `safety` has no history ("remains safe", "still").
- **Units and amounts**: a rate in pounds shown next to an amount in pence; a converted figure
  ("38p" for 0.38 GBP) is the data's only if the conversion is right and the reader can tell.
- **Selections**: facts are a selection (each says how it was picked in the issue's angle). "Two
  companies go ex-dividend", "the highest", "leads its sector" need a count or ranking the facts give.
- **The company**: its name right ("Interintek" was written once), the cashtag only for US tickers.
- **Tone**: hype ("shock", "soaring", "spiking"), filler ("holds a safe label for dividend safety"),
  near-duplicates of another version, a hint of advice ("look how cheap") by juxtaposing a price
  fall with a yield without saying why.

## 3. Check the data itself

The agent may not use outside knowledge; the review should. Flag, as something to verify at the
company's own source, not as fact, anything that looks wrong:

- Streaks: Quantic's stop at 29 years; a long-standing payer with a short streak (Microsoft's 15).
- Changes: a raise or cut in a REIT's or a semi-annual payer's rate that may be a timing swing; a
  listing whose rate moves with the exchange rate.
- Safety labels that sit oddly with the facts (a deep cut labelled safe).
- Prices and units: a London listing mixes pounds and pence.

The "Looked at and left out" list is the day's data-quality report: mention anything there worth an
issue on Quantic's side.

## 4. Report, in the terminal

For each company: the version to post (as written, or with a minimal edit, marked as edited), and
what's wrong with the others, one line each. Then the data flags, and anything time-sensitive
(post today: the price is as of the facts' date; an ex-date tomorrow). Remind the author to tick
the version they post, so `--sync` records it.

Only if the author asks for the review on the issue: `gh issue comment N -R fleveque/quantic
--body-file FILE`. Say first that it is posted from their GitHub account.
