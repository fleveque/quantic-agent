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
