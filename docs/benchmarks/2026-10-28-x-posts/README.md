# X posts from Quantic's data, 2026-10-28

Can the 27B write short posts for X from Quantic's public data, and can it check them? An
experiment, not a milestone: throwaway scripts using the agent's own modules (`quantic.Server`,
`llm.Client`, `provenance`, `wording`, `xpost.x_length`), on the machine of the
[other benchmarks](../README.md), Qwen3.8-27B `UD-IQ3_S`, `num_ctx` 32768, Ollama 0.34.4. The GPU
was otherwise idle. Every prompt is quoted [at the end](#the-prompts).

## The data

[`mcp/`](mcp/) is what code gathered from quantic.finance/mcp, anonymously: `dividend_changes`
(30 days), `dividend_calendar` (14 days), `earnings_calendar` (7 days), `screen_stocks` for each of
11 sectors sorted by quality and by yield, and the Dividend Kings and Aristocrats lists: 27 calls,
700 distinct symbols. Financial Services and Industrials hit the screener's 100-row cap.

[`facts.json`](facts.json) is what code computed from it, the only thing the writer sees: 55
facts. Raises and cuts of 1% or more, without second listings (`.F`, `.DE`, `.XC`), with each
change's percentage; companies with a streak of 10+ years going ex-dividend in the next 7 days;
a snapshot per sector (safety labels counted, median 5-year average yield and growth); the
fastest 5-year growers among safe companies with a 10+ year streak; safe companies with a 10+
year streak whose yield is at least 1.25 times their own 5-year average.

**What the data showed before any model ran**, all for Quantic to look at:

- Every streak stops at 29 years: the longest in the screener are APD, LIN, GPC, IBM, ADP, SWK,
  ITW and DOV, all at 29. The Dividend Kings list (50+ years) returns FRT at 29 and ABBV at 12.
  Streak facts were left out of `facts.json`.
- Most "cuts" are rounding: on 2026-10-16, T 1.112 → 1.11, NEE 2.492 → 2.49, SHEL 3.1248 → 3.12,
  HRL, ROL, SKT, AI.PA, BATS.L. 10 of the 14 cuts seen in 30 days were under 1%.
- Deep cuts labelled safe: Diageo −39.8%, Intertek −34.5%, PAX Global −75.8%. PAX keeps a 6-year
  streak of increases and Intertek a 3-year one next to their cuts.
- One company, several listings with different figures: MCD, MDO.F and MDO.DE (streaks 17, 14,
  17); Enagás's 5-year growth is −5.6% as ENGGY and −13.3% as ENG.MC.
- Names as stored: "CORPORACI...N ACCIONA ENERG...A", "Duke Energy Corporation (Holdin",
  "Zoetis Inc.                   R".
- Microsoft's streak is 15 years. It has raised every year since the early 2000s, so this looks
  low; not checked further.

## First try: who does the research

[`first-try/`](first-try/): 8 posts each way, figures checked by `provenance.check_prose`, wording
by `wording.check`, up to 3 attempts.

- **The model researches** (`model-researches.json`): the agent's research loop with
  `dividend_calendar`, `get_stock`, `dividend_changes` and a `screen_stocks` tool, budget 16 calls.
  It made 6 calls (52 s) and stopped. The posts were lists of two unrelated facts ("$MSFT has a
  15-year dividend streak. $NEE has a 29-year dividend streak."), repeated a 0.8% raise and a cut
  from a secondary listing, and converted a ratio into "10.230450734403207%".
- **Code gathers, the model writes** (`code-gathers.json`): varied, readable posts, every figure
  traced. About half had a claim no check sees: "first increase in its streak" and "first year of
  a new dividend streak" for a streak of 0, "hit an ex-dividend date of Oct 30" two days before
  it.

Both checks' flags that round were the checker's: "a 75.8% cut" against `change_pct` −75.8, and
the digits of `0327.HK`. The model "fixed" both by deleting the figure.

## Rounds 1 and 2: a verifier, measured

Each round is 12 writing runs (8 posts, seeds 1–12 and 13–24, facts shuffled per seed), keeping
the posts that passed the code checks. I (Claude, Opus 5.5) labelled every post blind, before the
verifier ran, and made the label files read-only; then the 27B verified each post claim by claim,
temperature 0, in a fresh conversation.

A post is **wrong** when a claim isn't supported by the facts. Major: a misspelled name, `seen_on`
given as the date of the change, a field misread, a ranking or count the data doesn't give, a
causal claim. Minor: an unsupported "remains"/"maintains"/"previously", an internal selection
presented as a list, the 5-year average yield called "yield", an invented explanation. **Data**:
the post repeats data that contradicts itself (a cut next to a running streak of increases).

| | Round 1 | Round 2 |
|---|---|---|
| Writer | the rules | plus what each field means, and no rankings or counts |
| Posts passing the code checks | 95 | 96 |
| Wrong, major / minor | 11 / 8 | 1 / 1 |
| Data only | 3 | 5 |
| Verifier sees | the post's facts, field meanings | every fact, field meanings, "seen on" is supported |
| Wrong or data posts flagged | 14 of 22 | 0 of 7 |
| Correct posts flagged | 10 of 73 | 1 of 89 |
| Seconds per verification, median | 9.8 | 10.9 |

[`round1/`](round1/) and [`round2/`](round2/) hold the writer runs (`writer-runs/`), the posts
with the facts each was checked against (`posts.json`), the labels (`labels.json`, with each
wrong post's reason) and the verdicts (`verdicts.json`).

- **The field meanings fixed it at the source.** `seen_on` read as the date of the change was 6 of
  round 1's 11 major errors; in round 2 posts say "seen on" or "Quantic first saw the new rate".
- **Round 1's verifier** caught 9 of 11 major errors. It missed a count it couldn't check (it saw
  only the named companies' facts) and one `seen_on` date it caught in four other posts. Of its 10
  false flags, 3 were "noted/recorded on" read as an announcement date, 5 called "maintained its
  dividend for 23 years" a different measure than a streak of increases (arguable), 1 a ranking
  true across all facts, 1 "a notable shift".
- **Round 2's verifier caught nothing**, and its one flag confused TXN's 7.0% with Microsoft's
  7.7%. Two things changed at once, all the facts (about 7k tokens of similar rows) and the note
  about "seen on"; this run can't separate them.
- **Round 2's two wrong posts can't be caught by a model given these facts**: "Two names go
  ex-dividend on 2026-10-28" is true of the facts (10+ year streaks only) and false of the
  calendar, which has four. The fix is in the facts: each says how it was selected.

## Round 3: a link, and catchy without spam

[`round3/`](round3/): the writer as in round 2, plus style rules (the hook first, one idea, no
exclamation marks, capitals, hashtags, teasers or questions to the reader, at most one emoji from a
fixed set) checked by code, and a link chosen by code from the facts a post cites: one company →
`/stocks/SYM`, whose page carries a `summary_large_image` card with Quantic's `og.png`; two →
`/compare/A,B`; several ex-dividends → `/dividend-calendar`; a sector → its list page. X counts
the link as 23 characters; every post with its link is at most 280. Each fact now carries how it
was selected, and cuts drop the contradicting streak.

- **`style-1/`**: correct and flat. Every post said "first seen on Oct N"; padding ("The safety
  label is 'safe'"); "changed by -75.8%", because "a 75.8% cut" still failed the figure check.
- **`style-2/`**: a positive `change_size_pct` per change, the date optional, three
  placeholder patterns. Better posts, and **three linked to the wrong company**: "Allwyn raised…"
  under CapLand's page, "Texas Instruments raised…" under Riley Permian's. The model cited wrong
  fact ids, and the figure check passed because it traced figures to every fact, not the post's.
- **`final/`**: figures traced only to the facts the post cites, and each cited company must be
  named in the text. Every run's first attempt cited the wrong facts (4 posts in 3 runs); all were
  corrected by the second. 24 posts, every link right.

What's still wrong in `final/` is wording, not figures: "extending its streak to 22 years" (the
data doesn't say this raise made it 22), "slashed" and "hiked". And Quantic's data behind the
cuts and the CapLand raise, above, needs checking before any of them is posted.

## Nike: one company, catchier

[`nike/`](nike/): five alternative versions of one post about Nike per run, asked to be catchier,
with the cashtag `$NKE` and emojis, and the link added by code. The facts come from
[`mcp/get-stock-NKE.json`](mcp/get-stock-NKE.json) and the screener, computed by code: a 4.37%
yield, 3.1 times the 5-year average and 1.88 times the 5-year high of 2.33%; 23 years of
increases; $0.48 a share in 2014 to $1.60 in 2025; the last known price, $37.56 on 2026-10-28,
77.8% below the 5-year monthly high of $169.24. From `2-prose/` on, also the estimated earnings
date (2026-12-17, from `earnings_calendar`), the payment months, and a ranking computed by code:
the highest yield of the 4 Consumer Cyclical companies in the screener with a 20+ year streak.
`get_stock_research` and `compare_stocks` refused anonymous calls, with a message saying they read
"a user's own portfolio", which neither does.

- **`1-list/`** ("short and punchy", two or three emojis): every version a list of fragments
  ("Yield: 4.37%. 5y avg: 1.41%. 📊"), jargon ("DPS", "3.33x dividend growth"), emojis stacked at
  line ends. "2014" was rejected each time: years were inside field names
  (`dividend_per_share_2014`), which the figure check doesn't read, so the model dropped them.
- **`2-prose/`** ("like a person who follows dividend stocks", one or two sentences, one
  invented example company): prose, 69–119 characters. Four faults were the checks': "Best Buy"
  matched the advice rule's "buy" (so does `wording.py` on `main`); the market rule's "price"
  pushed the model to "Nike shares traded at 37.56" and "the last known value"; "20+" lived in a
  string, so "20" was rejected and the model wrote a false "23+ year streaks"; a "12 months" term
  added for one fact let "over the last 12 years" through (2014 to 2025 is 11).
- **`3-fixed-checks/`**: company names masked before the wording rules, "price" allowed, the
  threshold a number (`min_streak_years`), the 11 years a fact, no "12 months" term; emojis
  stacked at the end and a short list of selling words checked. Runs 1 and 3 passed at the first
  attempt. Of 14 versions that passed, 5 had a claim no check sees: "pays its next dividend in
  March" (it pays in March, June, September and December; after October the next is December),
  "a 23-year streak … that started in 2014" (where Quantic's history starts), "23 years of
  dividend raises puts $NKE at 4.37% yield" (the yield is high because the price fell), "Nike
  shares are at $37.56" (the last known price as current), "earnings due 2026-12-17" (estimated).

Each fix removed one class of error and the model found the next assumption the facts left
unstated; each has the same kind of fix, the answer given as a fact (`next_payment_month`, where
the history starts). The version I'd post as written, run 1's third: "The 4.37% yield on $NKE is
more than triple the 5-year average, sitting well above the 2.33% high from that period 📊".

- **`4-hook-and-why/`**: two paragraphs, the hook and one sentence that explains or balances it;
  emojis only at the start of a paragraph (checked); new facts stated by code so the model
  needn't infer them: `next_payment_month` (December), where Quantic's dividend history starts,
  the annual dividend against its 5-year average (1.21 times, from a rate of $1.64 and the
  2021–2025 average), and `why_the_yield_is_high`, the only cause the model may give. That cause
  holds either way it's measured: the price is about 83% of the yield's rise against the 5-year
  average dividend, 57% against 5-year compound growth. Run 1's first attempt put emojis at the
  ends of sentences in all 5 versions; every final version opens its paragraphs with them. Of 15
  final versions, 6 I'd post as written (run 1's first: "👟 Nike ($NKE) yields 4.37%, well above
  its 5-year average of 1.41%. 📉 The share price is the main driver, as the annual dividend is
  only 1.21 times its 5-year average."), 3 are correct and bland, and 6 have a fault no check
  sees: "reported earnings on 2026-12-17" (estimated, in the future), "trades at $37.56" (the last
  known price as current), "the dividend stays near its 5-year mean" and "remains stable" (it is
  1.21 times), "This 23-year streak of increases supports the current yield" (the cause reversed,
  1 in 15 against 2 in 14 before), "safe despite the $NKE yield spiking", "This push the $NKE
  yield".

What the author posted on X from these rounds ([the post](https://x.com/quantic_es/status/2115408459311219055)), written by Claude from the facts, not by the agent: "📊 The
4.37% yield on $NKE is more than triple its 5-year average, and well above the 2.33% high from
that period. Much of that comes from the share price, 77.8% below its 5-year high, while the
dividend has now risen 23 years in a row." with the link to Nike's page.

## The prompts

Every writer's system message is `agent.SYSTEM_PROMPT`, and the facts come first in the user message. The rules after them, rounds 1 and 2 (`DEFS` only in round 2), with the posts as JSON through Ollama's `format`:

```
f"""Today is Wednesday {TODAY}.
Write 8 separate posts for X (Twitter) for a dividend data site. Rules:
- Each post stands alone, at most 260 characters, plain text, no hashtags, no links.
- Each post is about one or two facts from the data. Pick the most interesting ones and vary the topics.
- Every figure, date and name must come from the data, written as the data gives it (percentages as given; dates may be written like "Oct 30").
- Describe what the data shows. No advice: never suggest buying, selling, holding, or that something is cheap, a bargain, an opportunity or undervalued.
- Never address the reader ("you", "your", "investors", "readers").
- A cashtag like $KO is fine for US tickers.
{DEFS}Reply as JSON: {{"posts": [{{"facts": [ids or tickers used], "text": "..."}}]}}"""
```

```
"""- What the fields mean: streak_years = consecutive years of dividend INCREASES up to now (0 = no current streak);
  seen_on = the day Quantic first saw the new rate, NOT the day the company announced or changed it (write "seen on", never "raised on" or "cut on");
  change_pct = percent change of the annual rate; old_annual_rate/new_annual_rate = annual dividend per share before and after;
  safety = Quantic's dividend safety label now (safe/watch/at_risk), with no history; dividend_growth_5y_pct = 5-year annual growth rate of the dividend;
  yield_avg_5y_pct = the 5-year AVERAGE yield (call it that, not "yield"); yield_pct = the current yield;
  kind = how the fact was selected by code (fast_grower, yield_above_own_average...): a selection, not a list Quantic publishes.
- Don't rank, compare against companies not in the post, or count companies yourself ("the highest", "three companies"): the data gives no rankings.
"""
```

The verifier, round 1 (`FIELDS` as `{defs}`) and round 2 (`FIELDS` + `ROUND2_NOTE`):

```
"""Field meanings: streak_years = consecutive years of dividend increases up to now (0 = no current streak);
seen_on = the day Quantic first saw the new rate, not the announcement date; change_pct = percent change of the annual rate;
safety = Quantic's dividend safety label (safe/watch/at_risk); dividend_growth_5y_pct = 5-year annual growth rate of the dividend."""
```

```
"""
Saying a change was "seen", "noted" or "recorded" on seen_on is supported. The data below is ALL the facts available,
not only the ones the post uses: use it to check counts and comparisons."""
```

```
"""Today is Wednesday 2026-10-28. Below is a post written for X and the data it was written from.
Check the post claim by claim. A claim is supported only if the data states it directly; an interpretation, a
cause, a tense that contradicts the dates, or a description the data doesn't give is NOT supported. Also say if the
data itself looks inconsistent for what the post says.
{defs}
Data:
{facts}

Post:
{post}

Reply as JSON: {{"claims": [{{"claim": "...", "supported": true/false, "why": "..."}}], "data_inconsistent": "..." or ""}}"""
```

Round 3's writer, as in `final/`, with the selection notes added to each fact:

```
f"""Today is Wednesday {TODAY}.
Write 8 posts for X (Twitter) for Quantic, a dividend data site, each about one fact (or two closely related ones) from the data.
Code puts a link to the matching Quantic page on its own line after each post: don't write links, "link below" or "more on Quantic".

What makes a good post:
- Open with the hook: the most striking figure or contrast in the fact, in the first few words.
- One idea, one to three short sentences, at most 220 characters.
- Plain, confident and factual. Vary the topics and the openings across the 8 posts.
- Every detail must add to the hook. Leave out fields that don't ("The safety label is 'safe'", "The streak is 0 years").
- The seen_on date is optional and usually better left out.
- Currencies once each: "$1.04", "€0.70", "£1.08", "HK$0.08", "S$0.15", never "$0.15 SGD".
- Patterns that work (placeholders, not data):
  "A <size>% raise: <Company> lifted its annual dividend from <old> to <new>."
  "<Company> now yields <yield>%, <times> times its 5-year average of <avg>%. <streak> straight years of increases."
  "<Company> goes ex-dividend on <date>: <streak> years of increases, <yield>% yield."
- Company names as people say them: "Texas Instruments", not "Texas Instruments Incorporated"; "Intertek", not "INTERTEK GROUP PLC ORD 1P".
- A cashtag like $TXN only for tickers without a dot; other companies by name.

What makes a post look like spam, never do it:
- Exclamation marks, words in capitals, hashtags, "BREAKING", questions to the reader, teasers ("here's why", "you won't believe", "the numbers tell a story").
- More than one emoji. One is fine when it fits, only from: {" ".join(EMOJI)}.

Accuracy:
- Every figure, date and name comes from the data, as the data gives it (dates may be written like "Oct 30").
- What the fields mean: streak_years = consecutive years of dividend INCREASES up to now; seen_on = the day Quantic first saw the new rate,
  NOT the day the company announced or changed it (say "seen on", never "raised on" or "cut on"); change_pct = percent change of the annual rate;
  old_annual_rate/new_annual_rate = the annual dividend per share before and after; safety = Quantic's dividend safety label now, with no history;
  dividend_growth_5y_pct = 5-year annual growth rate of the dividend; yield_avg_5y_pct = the 5-year AVERAGE yield; yield_pct = the current yield;
  selection = how code picked the fact: never present a selection as complete, and don't count or rank companies yourself.
- Describe what the data shows. No advice: never suggest buying, selling or holding, or that something is cheap, a bargain, an opportunity or undervalued.
- Never address the reader ("you", "your", "investors", "readers").

Reply as JSON: {{"posts": [{{"facts": [the ids of the facts used], "text": "..."}}]}}"""
```

```
{
    "raise": "a change of 1% or more in the annual rate that Quantic saw in the last 30 days",
    "cut": "a change of 1% or more in the annual rate that Quantic saw in the last 30 days",
    "ex_dividend_soon": "one of the companies with a 10+ year streak going ex-dividend in the next 7 days; other companies go ex-dividend too",
    "fast_grower": "picked by code: safe, a 10+ year streak, and among the highest 5-year dividend growth of those",
    "yield_above_own_average": "picked by code: safe, a 10+ year streak, current yield at least 1.25 times its own 5-year average",
    "sector_snapshot": "the companies in Quantic's screener for this sector, not the whole market",
}
```

When a post breaks a rule, the writer is sent `Some posts break the rules:`, one line per post with
its problems, and `Reply with all 8 posts again, fixing those. Same JSON format.`

Nike, `1-list/` (`EMOJI` is "👟💰📈📉🔥🧾💵📊📅🔍"; the facts come first, as JSON):

```
f"""Today is Wednesday {TODAY}. Write 5 alternative versions of one X (Twitter) post about Nike for Quantic, a dividend data site,
from the data below. Code adds the link to Nike's page on Quantic on its own line after the post: don't write a link.

Make it catchy:
- Open with the strongest hook in the data: a striking figure or contrast, in the first words.
- Short and punchy: two to four short lines, at most 200 characters. Line breaks are fine.
- Include the cashtag $NKE once.
- Use two or three emojis that fit, only from: {" ".join(EMOJI)}.
- Make the 5 versions different: different hooks and structures, not rewordings.

Never look like spam: no exclamation marks, no words in capitals, no hashtags, no "BREAKING", no questions to the reader,
no teasers ("here's why", "you won't believe", "the numbers tell a story").

Accuracy:
- Every figure and date comes from the data, as the data gives it.
- streak_years = consecutive years of dividend increases. safety = Quantic's dividend safety label.
- last_known_price is the last price Quantic saw, on last_known_price_as_of: don't call it current or live; price_high_monthly_5y is the
  highest monthly price in the last 5 years.
- Describe what the data shows. No advice: never suggest buying, selling or holding, or that something is cheap, a bargain, an
  opportunity, undervalued or a dip. Never address the reader ("you", "your", "investors", "readers").

Reply as JSON: {{"posts": ["...", "...", "...", "...", "..."]}}"""
```

Nike, `3-fixed-checks/` (`2-prose/` is the same without the selling language and the emoji placement), and the selling words it checks:

```
f"""Today is Wednesday {TODAY}. Write 5 alternative versions of one X (Twitter) post about Nike for Quantic, a dividend data site,
from the data below. Code adds the link to Nike's page on Quantic on its own line after the post: don't write a link.

Write it like a person who follows dividend stocks, not like a data feed:
- One observation, told in one or two natural, complete sentences, with the two or three figures that make it interesting. Not a list of figures. No selling language ("income potential", "impressive", "significant").
- At most 200 characters. Plain words: "5-year average", never "5y", "avg", "DPS" or "x" for times.
- Include the cashtag $NKE once, as part of a sentence.
- One or two emojis that fit, placed where they add meaning (at the start, or next to the figure), never stacked at the end, only from: {" ".join(EMOJI)}.
- Make the 5 versions tell different stories from the data (the yield, the long record of raises, the price, the ranking in its sector,
  the next earnings date...), not rewordings of one.

For example, about another company (made up, not data): "Northwind has raised its dividend every year since 2009, and at 3.2% its
yield now sits above anything it paid in the last five years 📈 $NWND" — a story, not a list like "Yield: 3.2%. Streak: 17. 📈💰".

Never look like spam: no exclamation marks, no words in capitals, no hashtags, no "BREAKING", no questions to the reader,
no teasers ("here's why", "you won't believe", "the numbers tell a story").

Accuracy:
- Every figure and date comes from the data, as the data gives it.
- streak_years = consecutive years of dividend increases. safety = Quantic's dividend safety label.
- last_known_price is the last price Quantic saw, on last_known_price_as_of: don't call it current or live; price_high_monthly_5y is the
  highest monthly price in the last 5 years.
- Describe what the data shows. No advice: never suggest buying, selling or holding, or that something is cheap, a bargain, an
  opportunity, undervalued or a dip. Never address the reader ("you", "your", "investors", "readers").

Reply as JSON: {{"posts": ["...", "...", "...", "...", "..."]}}"""
```

```
re.compile(r"\b(?:income potential|significant|impressive|remarkable|juicy|stunning|massive|huge|solid|strong|eye-catching)\b", re.I)
```

Nike, `4-hook-and-why/`, with the same spam rules and checks plus emojis only at the start of a paragraph:

```
f"""Today is Wednesday {TODAY}. Write 5 alternative versions of one X (Twitter) post about Nike for Quantic, a dividend data site,
from the data below. Code adds the link to Nike's page on Quantic on its own line after the post: don't write a link.

Write it like a person who follows dividend stocks, not like a data feed. Each version has two short paragraphs:
1. The hook: one sentence with the most striking figure or contrast.
2. One sentence that explains or balances it, using why_the_yield_is_high, the price, or the record of raises. Never explain
   anything the data doesn't state: why_the_yield_is_high is the only cause you may give.
- 140 to 240 characters in all. Plain words: "5-year average", never "5y", "avg", "DPS" or "x" for times.
- Include the cashtag $NKE once, as part of a sentence. No selling language ("income potential", "impressive", "significant").
- One or two emojis, only at the very start of a paragraph, never at the end of a sentence, only from: {" ".join(EMOJI)}.
- Make the 5 versions open with different hooks, not rewordings of one.
- Use "estimated" with the earnings date and "last known" with the price. 2014 is where Quantic's dividend history starts, not the streak.

For example, about another company (made up, not data): "📈 Northwind ($NWND) now yields 3.2%, above anything it paid in the last five years.

Most of that is the share price, while the dividend has risen every year since 2009." — a story, not a list like "Yield: 3.2%. Streak: 17. 📈💰".

Never look like spam: no exclamation marks, no words in capitals, no hashtags, no "BREAKING", no questions to the reader,
no teasers ("here's why", "you won't believe", "the numbers tell a story").

Accuracy:
- Every figure and date comes from the data, as the data gives it.
- streak_years = consecutive years of dividend increases. safety = Quantic's dividend safety label.
- last_known_price is the last price Quantic saw, on last_known_price_as_of: don't call it current or live; price_high_monthly_5y is the
  highest monthly price in the last 5 years.
- Describe what the data shows. No advice: never suggest buying, selling or holding, or that something is cheap, a bargain, an
  opportunity, undervalued or a dip. Never address the reader ("you", "your", "investors", "readers").

Reply as JSON: {{"posts": ["...", "...", "...", "...", "..."]}}"""
```
