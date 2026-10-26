# 0018 — The week's X post: drafted by code, in the pull request, posted by the author

**Status:** accepted · **Date:** 2026-10-26

## Context

On 2026-10-26 the author posted the first Week Ahead on X (@quantic_es), from a draft written in a
chat: the counts, two raises, a cut, the link, cashtags and two hashtags. They asked for the agent to
draft it every week. Design's non-negotiables hold: no autonomous publishing (the agent posts
nothing, anywhere) and no invented numbers.

## Decision

The author chose three things:

1. **Code writes it, from the data block, not the model** ([`xpost.py`](../../src/quantic_agent/xpost.py)).
   A fixed template:
   - the week's dates;
   - how many companies go ex-dividend, with cashtags for the two US listings with the longest raise
     streaks (X makes cashtags of US-style tickers only);
   - the two biggest raises and the biggest cut of 1% or more, a percentage worked out from a
     change's two rates as the page does. Smaller changes are mostly a listing's rate moving with
     the exchange rate (quantic#509);
   - how many companies report;
   - the link to the post on quantic.finance;
   - `#DividendInvesting #Dividends`.

   Every figure in it is the data's by construction, and it reads the same each week. The model
   writing it, held to the data by the prose checks, was the alternative: livelier, but one more
   text to review weekly, and unmeasured.
2. **It goes in the pull request's description**, a `text` block with its length, which the author
   copies when they merge. Nothing is stored or sent elsewhere.
3. **In English, linking to quantic.finance**, as the first post did. X offers its own translation.

**It fits X's limit by construction.** `x_length` counts as X does: a link is 23, a code point
outside the light ranges (emoji, CJK) is 2, every other one 1. `draft` drops lines in a fixed order
until the post is at most 280: the earnings count, then the cut, the raises and the hashtags.

## Consequences

- **The draft is built when the pull request opens,** from the data the agent wrote. A reviewer who
  edits the data block before merging (W44 lost four rows) has to check its counts. The description
  says so.
- **"Biggest raise" is by percentage,** so it can name small companies: W44's draft names Allwyn
  (+40%) and ASA (+25%), where the author's chose West Pharmaceutical (+18%) and Western Digital
  (+17%). It's a rule, and it can be changed.
- **No post leaves the machine:** this adds text to a pull request the App already opens.
