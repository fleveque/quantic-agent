# Lesson 19 — What I posted, as examples

**Milestone 19**: the daily writer is now shown up to three posts I actually published before it
writes about a company: the same angle first, then the newest, never the same company, and an
edited one as its draft next to what I posted. I measured it before merging, and on everything the
checks can see it changed nothing. That's the most useful thing this milestone taught me.

*Also readable as a [formatted page](https://claude.ai/artifact/PLC4iEwTsgRkRYyrCrRn4r), with a [code walkthrough](https://claude.ai/artifact/Pc1GkCaXJnyDtBNRocqxBy) of every
change the milestone made.*

---

## Two sources, one list

Milestone 18 stored posts in two places: a ticked version is a `proposals` row with `posted_at`,
and an edited or written-from-scratch post is an `issue_comments` row. `Store.posted_texts` makes
them one list of `PostedText`, newest first. A comment replaces its run's tick for the same
company, because the comment says what actually went out. The edited post's draft comes from a
`LEFT JOIN` on the version it names. A post written from scratch has no version to join, so its
draft is `None`, and so is its angle when the issue never proposed that company.

`daily.py` had never imported `store.py`. It can now, for the one type, because `store` doesn't
import `daily`: no cycle. The alternative was a second dataclass in `daily` and a conversion in the
CLI, three types for one idea.

## Picking is two list comprehensions

```text
other = [p for p in posted if p.symbol != facts.symbol]
ordered = [p for p in other if p.angle == facts.angle] + [
    p for p in other if p.angle != facts.angle
]
```

Because `posted` is already newest first, each half keeps that order: "same angle first, then the
newest" needs no sort key. In Elixir I'd have reached for `Enum.split_with/2`, which does the
same split in one pass. Then each pick goes through `dataclasses.replace`, Python's version of
`%{post | text: ...}`, to drop the link (code adds it) and to forget a "draft" that only differed by
the link.

## The examples carry no facts

The examples go in the writer's first message, before the data, labelled "tone and structure only;
their figures, dates and names belong to those companies". The label isn't the safety, though.
`check_version` traces every figure to *today's* company's facts, so a Brown-Forman "3.18%" in a
Nike post is sent back like any invented figure. That's also why the company's own old post is
never an example: its old figures might still match.

## Measured: no change

Ten companies from runs 8–13, re-written twice with and without examples on the 27B:

| | Baseline | Examples |
|---|---|---|
| Needed a retry | 13 of 20 | 12 of 20 |
| First-attempt problems | 24 | 24 |
| Held versions | 0 | 5 |

The 5 held looked like a regression, so I re-ran the four companies that had them, with the
problem texts recorded. None were held, and the figure problems were the writer's own arithmetic
("1.5", "17%", "3.19%"), not copies. My check for copied figures had one false hit of its own: "3%"
is a substring of "5.73%".

Copying turned out to be about phrasing: six writes reused a 5-word phrase from an example, like
Entergy's "per year over the last five". And Nike's posts with examples named the company as
"Nike ($NKE)", as four of the five posted texts name theirs, where the baseline wrote "$NKE"
alone.

## Why nothing moved

Four of my five posted texts were ticked as written: they're the agent's own drafts. Showing the
writer its own output teaches it to write like itself. Only Brown-Forman carries an edit of mine.
The feature gets its value from edits, and I've made one. So it ships as plumbing that costs
2 seconds a write, recorded per run, to be measured again once a few weeks of edited posts exist.

Lesson 17 found that telling the translator the right terms did nothing and the retry did
everything. This is the same lesson from the other side: the checks were never going to show style,
and a benchmark that only counts what checks see can't tell me whether the posts read better.
I'll find that out on the issue.
