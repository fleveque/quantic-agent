# Lesson 16 — A shortlist every morning

**Milestone 16** — every weekday at 07:30 the agent drafts X posts about a few companies and opens
them as a GitHub issue: three versions of each, checked, with the facts they were written from. I
pick one, post it myself, and tick its box. The day before, an experiment had shown me what the
model is for, and what it isn't: it writes facts up well, and finds them badly. So this milestone
is mostly code that does the finding.

*Also readable as a [formatted page](https://claude.ai/artifact/JsApe2npz8oRro34bP7R62), with a [code walkthrough](https://claude.ai/artifact/Xt7zTAyHXogmMVx5tAnyUH) of
every change the milestone made.*

---

## The experiment came first

Before writing any of this, Claude and I measured it
([benchmark](../benchmarks/2026-10-28-x-posts/README.md)). Given Quantic's tools and asked to find
something worth posting, the 27B made six calls and wrote lists: "$MSFT has a 15-year dividend
streak. $NEE has a 29-year dividend streak." Given facts that code had computed, it wrote posts I'd
read. And once the prompt said what each field means, wrong claims went from 19 of 95 posts to 2 of
96. The biggest single error had been reading `seen_on`, the day Quantic noticed a new rate, as the
day the company raised it.

That decided the shape: code does the research, the model writes, code checks, and I choose.

## Code picks the companies

`daily.py` makes the same three calls every day (raises and cuts, the coming ex-dividends, one
screen of safe companies with long streaks) and ranks candidates for three angles: a dividend
change, an ex-dividend, a yield well above the company's own average. Then it looks them up one at
a time until one is good enough:

```
reason = accepts(candidate, stock)
if reason is None:
    accepted.append((candidate, stock))
    break
rejected.append(Rejected(candidate.symbol, stock.profile.name, angle, reason))
```

`accepts` uses `match` on the angle, an enum: `case Angle.CHANGE:` is a value pattern, a dotted name
compared with `==`. A bare name would be a capture pattern instead, binding anything, so Python
insists on the dot. Elixir has the same trap the other way round: a bare variable rebinds, and you
pin it with `^`.

The rejected list goes into the issue, and it turned out to be the day's data-quality report. On
the first day: Intertek's 34.5% cut next to a three-year streak of increases that was "still
running", which can't both be true. CapLand's 36% raise from a company with no streak. I'd never
have seen those otherwise.

## Pence are not pounds

Code computes the facts the writer sees, in two kinds: values copied from a tool, which are checked
against the stored calls as any data is, and values derived from them, like a change's percentage.
Reading BAE Systems' facts, I found it 99.1% below its five-year price high. It isn't: the last
price was 20.17 in pounds, the high 2187.0 in pence. The dividend history was in pence too, next to
a rate of £0.38. Quantic's data mixes the units for London listings, and every figure "traced".

So amounts more than twenty times apart aren't shown side by side:

```python
def same_units(a: float, b: float) -> bool:
    return a > 0 and b > 0 and 1 / UNITS_APART <= a / b <= UNITS_APART
```

Python chains comparisons: `1 / 20 <= a / b <= 20` is one test, and `a / b` is computed once. In Go
or Ruby that's two comparisons joined by `&&`.

## Telling the model the cause

The model's worst habit in the experiment was inventing reasons: "23 years of dividend raises puts
$NKE at 4.37% yield", backwards. So when the price explains most of a high yield, code says so, as
a fact: `why_the_yield_is_high`. Yield is dividend over price, so the two ratios multiply, and the
price explains more than half when the yield's ratio is more than the dividend's squared. For any
other company, a post with "because", "due to" or "reflecting" in it is sent back.

The checks grew the same way the Week Ahead's did: from what the model actually wrote. "38p" for a
rate of 0.38 GBP passed the figure check, because a number glued to letters reads as a word (so
"5y" isn't taken for a figure), so there's a check for that now. So is "trades at" for the last
known price. Each one came from a real post.

## A `$` in a text file

The prompt lives in `prompts/daily_post.md`, filled in by `string.Template`, whose placeholders are
`$name`. I added an example post with a cashtag in it, `($NWND)`, and every run stopped:

```
KeyError: 'NWND'
```

In a Template, a literal dollar is `$$`. Ruby's `format` and Python's `str.format` have the same
issue with `%` and `{}`. A test now renders the prompt, which would have caught it before any run
did.

## The test that never ended

One test hung for two minutes. It built a list from what a fake server had been asked:

```
for s in server.asked
```

and each pass called the server, which appended to `server.asked`. A Python `for` over a list
reads it as it goes, so the list kept growing. Go's `range` over a slice would have stopped,
because it evaluates the slice once. Ruby's `each` would have kept going too. Iterate over a copy (`list(...)`), or
don't call the thing that changes the list.

## Not reading the clock

"Not proposed in the last seven days" first counted from `datetime.now()`. The 2026-10-26 lesson
was that tests mustn't depend on the real clock, so it counts from the day being drafted, at local
midnight:

```python
from datetime import date, datetime, timedelta

day = date(2026, 10, 28)
since = datetime.combine(day - timedelta(days=7), datetime.min.time()).astimezone()
```

`astimezone()` with no argument attaches the machine's own zone to a naive datetime, which is what
the store's timestamps are compared in.

## An issue, not a publish button

The GitHub App can create an issue and read it back, and nothing else: no method edits, comments on
or closes one. When I tick "posted NKE version 2" and close the issue, `--sync` reads the ticks and
records them. A box I untick is unrecorded again: the issue is my record, the database mirrors it.

## What I'm taking on

- Measure what the model is for before building around it. Here: writing, not finding.
- Give the model the answers it would otherwise guess: field meanings, the cause, the next payment
  month.
- A figure that traces can still be wrong: units, signs, the wrong company's facts. Trace a post to
  its own company's facts.
- The companies a rule rejects are a report on the data. Show them.
- Every check came from a real post. The list will keep growing, and I still read every post before
  I put my account's name on it.

---

**Previous:** [Lesson 15 — Words the post can't use](15-words-the-post-cant-use.md)
