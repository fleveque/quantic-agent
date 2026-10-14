# Lesson 15 — Words the post can't use

**Milestone 15** — the prose is checked for wording, not just figures. The prompt has always said
"never recommend" and "never count the companies", and the model has always done both
sometimes: "offering distinct profiles for income-focused investors", "Both companies maintain
long histories". Now a list of rules catches those phrases and sends them back to the writer, the
way a figure is. I learned more from measuring it than from writing it.

*Also readable as a [formatted page](https://claude.ai/artifact/KcQeXD23ncBeX1kU94Nmx2), with a [code walkthrough](https://claude.ai/artifact/DnRLm51mYFbyMH3idu2ZDT) of every
change the milestone made.*

---

## A rule is data

Each rule is a name, a pattern and the instruction the writer gets when it breaks it:

```python
Rule(
    "audience",
    _words(r"investors?", r"readers?", r"income[- ](?:focused|oriented|seekers?)", r"you", r"your"),
    "Don't address the reader or name an audience: describe the companies.",
)
```

Five of them, in a tuple: audience, advice, market, count, duration. `_words` joins the alternatives
into one pattern, `\b(?:investors?|readers?|...)\b`, case-insensitive. In Go this would be a slice
of structs with a `*regexp.Regexp` in each, compiled once at package level with `MustCompile`.
In Elixir, a module attribute with `~r//i` sigils. Same idea in all three: the rules are a table,
and the code that applies them doesn't change when the table does.

## `\b` does more than it looks

`\b` is a word boundary: the point between a word character and anything else. That's what makes
`consider(?:ing)?` match "considering" but not "considered", where "consider" is followed by "ed"
and there's no boundary. It's also why "buyback" doesn't match "buy", and "someone" doesn't match
"one". I broke it on purpose by removing the `\b`s: five tests failed, the published quantic#492
prose among them. It says "increasing payouts", and without the boundaries the audience rule
found "you" inside "payouts".

## A finding is a finding

The figure check already had everything a phrase needs: a `Finding` sent back to the writer, held
after three attempts, stored with the draft, re-checked by `--run N`. So a phrase is a `Finding`
too, of a new kind:

```python
class Kind(StrEnum):
    NUMBER = "number"
    DATE = "date"
    YEAR = "year"
    PHRASE = "phrase"
```

No migration: findings are stored as JSON, and the new kind is one more string. Pyright found
the cost straight away. Two `match` statements over a figure's kind no longer covered every case:

```
error: Cases within match statement do not exhaustively handle all values
    Unhandled type: "Literal[Kind.PHRASE]"
```

A figure is never a phrase, so those two now say so with `raise AssertionError(...)`. Go's
`switch` checks nothing like this unless a linter does. Elixir's `case` raises a
`CaseClauseError` at run time. Here a strict type checker caught it before anything ran.

## Measuring it

I wrote W43's prose 60 times with the 27B, from run 3's recorded data, and kept every writing.
22 of the 60 had wording the first rules name. Then I read every match in context, which is the
part that mattered:

- "investors", 9 times. All of them addressed an audience, and two were advice: "investors should
  note the tight liquidity warning".
- "both", 12 times. Ten counted the companies. Two were "both X and Y", which is good English. The
  prompt forbids "both" in any use, so the rule does too, and a retry costs seconds.
- "one" and "single", 6 times, all counts, and "dominated by a single name, Apple" was false too.

With the check in the writer's loop, 60 more writings: all 60 published, 18 at the second attempt
and 4 at the third, 13 seconds a writing instead of 9. Then I read the 22 that were retried, and
the model had found other words: "offering exposure to technology and utilities", "warrants a
closer look", "a dynamic to monitor", "for over a decade". I added those, and the next 60 had two
more I hadn't seen: "Readers should note that…" and "warrants closer attention".

That's what a list is. Each round of measurement finds a few more wordings. What it guarantees is
narrow: a phrase it names is never published. Everything else is still my review.

## What I left out, and why

Reading the matches also told me what not to add. "The only companies going ex-dividend" appeared
13 times. It claims the list is complete, it was true every time, and it isn't a count. "The
broader market awaits earnings reports" is narrative. "Warrants" alone describes the data
("warrants a watch status"), so only "warrants attention" and "warrants a closer look" are rules.
A rule bans a word in every sense, so it should come from real writings, not from a guess at what
a model might say.

## What it can't see

"Each name carries a safe profile", with Iberdrola on watch. No rule can catch that: the words are
fine, and the claim is false. Checking claims against the data is a different check, and it's
still open.

## What I'm taking on

- When the instruction is in the prompt and the model ignores it some of the time, check it in
  code.
- Read every match before deciding a rule. A count tells you how often; reading tells you whether
  it's right.
- A model sent back finds other words. Measure again after every change.
- A new enum member is a change to every `match` over it. Let the type checker find them.
- A list of phrases guarantees those phrases, and nothing more. Say so.

---

**Previous:** [Lesson 14 — What I changed before merging](14-what-i-changed-before-merging.md)
