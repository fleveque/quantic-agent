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

The review goes on the issue as one comment (step 4): the author chose that, so the verdicts sit
next to the versions they judge (2026-10-29). The author posts on X themselves. Never post, and
never edit the issue's body, tick a box or close the issue.

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

## 3. Check the data against outside sources

The agent may not use outside knowledge; the review must. Check every fact a recommended version
states, and anything else that looks wrong, with WebSearch: the company's own release or filing
first (investor relations, SEC, the exchange), a quote page for prices. Say what each source
confirms, contradicts or leaves open, and link it. A figure no source confirms is "not confirmed",
never assumed right. On 2026-10-29 this found Hitachi's "annual rate" of 64 JPY to be its raised
interim dividend (32 yen) times two, and Realty Income's 28-year streak to be over 31.

What has gone wrong before:

- Streaks: Quantic's stop at 29 years; a long-standing payer with a short streak (Microsoft's 15).
- A semi-annual payer's "annual rate": the latest payment times two, so an interim raise reads as
  an annual one (Hitachi).
- Months: until quantic#521 is done, `payment_months` are mostly ex-dividend months. A post saying a
  company pays in a month needs checking, above all for Japan and the UK (Hitachi goes ex in March
  and September and pays months later).
- Changes: a raise or cut in a REIT's or a semi-annual payer's rate that may be a timing swing; a
  listing whose rate moves with the exchange rate.
- Safety labels that sit oddly with the facts (a deep cut labelled safe).
- Prices and units: a London listing mixes pounds and pence.

The "Looked at and left out" list is the day's data-quality report: mention anything there worth an
issue on Quantic's side.

## 4. Comment on the issue

Write the review to a file in the scratchpad and post it as one comment:

```sh
gh issue comment N -R fleveque/quantic --body-file FILE
```

`gh` is signed in as the author, so the comment is theirs; say so in the terminal. Start it with
`## Review (Claude)`, then one section per company:

- **The version to post**, in a `text` block ready to copy: as written, or edited, with what was
  edited and why. When the data is wrong, say not to post the versions as written; a replacement
  may use a source's figures, named as the source's, not Quantic's.
- **Each other version**, one line: what's wrong with it.
- **What the sources say** about its facts, linked; "not confirmed" where none did.
- **Anything time-sensitive**: an ex-date tomorrow, a price to check again if posted later.

End with "For Quantic's data": what looked wrong, the "Looked at and left out" list included.

A version posted with small edits is ticked; one rewritten past its version is left unticked, so
the record doesn't claim a text that wasn't posted. Say which in the terminal.

## 5. Report, in the terminal

The comment's link, the recommended version per company in a line each, and what the sources
changed. Not the whole comment again.
