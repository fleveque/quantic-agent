# 0019 — Daily X posts: drafted by code and the model, reviewed in an issue, posted by the author

**Status:** accepted · **Date:** 2026-10-28

## Context

The experiment of 2026-10-28 ([benchmark](../benchmarks/2026-10-28-x-posts/README.md)) asked
whether the 27B could find and write X posts from Quantic's data. Given the tools, it made 6 calls
and wrote lists of facts. Given facts computed by code, it wrote readable posts, every figure
traced; told what each field means, wrong claims fell from 19 of 95 posts to 2 of 96; given the
cause of a high yield as a fact, it stopped inventing causes in most versions. The author posted
one of the drafts (Nike's) on X the same day, and asked for this every day, with fresh data. The
design's non-negotiables hold: the agent publishes nothing (N2) and invents no figure (N1).

## Decision

The author chose:

1. **Every weekday, by itself**: `quantic-agent --daily`, on a systemd timer of its own (Monday to
   Friday, 07:30), not the Sunday `--weekly`. The data a post is built on changes daily (ex-dates,
   raises Quantic sees, the last known price behind every yield).
2. **One GitHub issue a day, on the Quantic repository**, which is private: drafts about named
   companies stay unseen until the author posts one. Each version has a box to tick when posted;
   `--sync` reads the ticks back. The App's new permission is **Issues: read and write**, and the
   client only creates an issue and reads it: it never edits, comments on or closes one. The author
   closes it.
3. **Claude reviews before posting**, when asked, in the terminal, with the project skill
   `.claude/skills/review-posts/`: each version against its facts and the errors the experiment
   found. A comment on the issue only when the author asks for one.
4. **A few companies a day, one per angle**, and none proposed in the last 7 days.

How it's built ([`daily.py`](../../src/quantic_agent/daily.py)):

- **Code does the research.** The day's first calls are fixed: `dividend_changes` (3 days),
  `dividend_calendar` (5 days, so a Friday reaches Tuesday) and one `screen_stocks` of safe
  companies with a streak of 10+ years. Code ranks candidates for each angle and looks them up
  with `get_stock` until one is accepted, at most 6 per angle:
  - **a dividend change** of 1% or more, the largest first, from a company with a streak of 5+
    years; a cut next to a streak that is still running is the data contradicting itself, and left
    out;
  - **an ex-dividend** in the next two weekdays, yield at most 8%, streak 10+;
  - **a yield** at least 1.25 times the company's own 5-year average, the furthest above first.

  Secondary listings (`.F`, `.DE`, `.XC`…) are skipped. The companies left out go into the issue
  with the reason: often a sign of Quantic's data.
- **Facts are computed by code**, in two kinds: values copied from the tools, checked against them
  (`provenance.check_data`), and values derived from those: a change's percentage, a yield against
  its own band, the next payment month, and `why_the_yield_is_high`, stated only when the price
  explains most of the rise (yield ratio > dividend ratio²). Amounts more than 20 times apart aren't
  shown together: BAE's last price is in pounds and its history in pence.
- **The model writes 3 versions per company**, two short paragraphs each, from a prompt that says
  what every field means ([`daily_post.md`](../../src/quantic_agent/prompts/daily_post.md)).
- **Each version is checked by code** and sent back with what's wrong, up to 3 attempts, keeping
  those that passed: figures traced to *its own company's* facts (the experiment's posts linked to
  the wrong company when they traced to all facts); the wording rules, with "price" allowed and the
  company's name masked ("Best Buy" isn't advice, fixed for the Week Ahead too); a cause only when
  the data states one; the last known price never as current; numbers with glued units ("38p");
  plain words; the cashtag once, when X makes one; one or two emojis from a fixed set, each opening
  a paragraph; no spam markers; at most 240 characters, and 280 with the link as X counts it.
- **The link is code's**: `quantic.finance/stocks/SYM`, whose page X shows as a card.

## Consequences

- **The author reviews every post.** The checks catch what a rule can name; the experiment and the
  first real run both had versions with a claim no check sees ("as the price is down 23.2%" as a
  cause, a near-duplicate). The issue is a shortlist, not a queue to publish from.
- **A day is drafted once.** `--daily` again on the same day leaves an answered day alone, says why
  for a day with nothing to post (exit 5) or no version passing (exit 4), and drafts again only a
  run that failed or was stopped.
- **The repeat window is the agent's memory of what it proposed**, not of what was posted: a company
  proposed and not posted waits 7 days too.
- **A daily run's record is the audit trail**: every call, every version proposed or held with what
  held it, and the issue's text; `--run N` re-checks them.
- **Every day uses the GPU for about a minute** (51 s on 2026-10-28, three companies), behind the
  same GPU check as `--weekly`.
