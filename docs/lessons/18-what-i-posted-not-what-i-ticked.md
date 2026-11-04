# Lesson 18 — What I posted, not what I ticked

**Milestone 18**: `--sync` keeps what I actually posted on X, and Claude's review, from a daily
issue's comments. On quantic#542 I posted Pfizer's first version as written and Brown-Forman's
second with the review's edits. The tick recorded Pfizer. Brown-Forman, and the review that found
its streak was 38 years where the company says 42, existed only on GitHub. Now both are in the
store, next to the versions they started from.

*Also readable as a formatted page, with a code walkthrough of every change the milestone made.*

---

## A tick can't say what I changed

A checkbox is a boolean. `--sync` already mirrored it into `proposals.posted_at`, and that was
enough for "version 1 went out as written". It couldn't say "version 2 went out with its second
paragraph rewritten", and it couldn't say anything for a post with no version at all (Hitachi's on
quantic#515, written from the company's own release). Milestone 14 had the same gap for the Week
Ahead and closed it by diffing the merge commit. An X post has no merge commit: X is the only
other copy. So I tell the agent, in a comment:

````text
posted BF-B version 2

```text
📊 Brown-Forman yields 3.18%, nearly double its 5-year average of 1.65%.

https://quantic.finance/stocks/BF-B
```
````

With that, ticks change meaning slightly: a tick now means *exactly as written*. Anything edited
gets a comment instead.

## The first line says what a comment is

The review and my posts are both comments from my account: `gh` is signed in as me when Claude
posts the review. So the author can't tell them apart, and `read_comment` looks at the first line
instead. `## Review (Claude)` is a review, kept whole. `posted …` is a post, parsed with one
`re.fullmatch`: symbol, an optional `version N`, then the `text` block and nothing after it.
Anything else ("Thanks!") is `None` and ignored.

The case I cared about is a comment that *starts* like a post but isn't one, because that's a typo
of mine. It raises `daily.NotRead`, and `--sync` names it with its link instead of keeping
something half-parsed. In Elixir I'd have returned `{:error, reason}` and matched on it; in Go,
`(Comment, error)`. Python's version is an exception class of my own, a `ValueError` subclass, which
the caller catches by name. Returning a string for "skipped" would have type-checked too, and
been one more thing every caller had to remember.

`fullmatch` is the point of the regex. `match` anchors only the start, so "posted BF-B version
2 … and PFE too" would have matched and lost the second post silently. With `fullmatch`, text
after the block is a `NotRead`.

## CRLF, which I'd never have typed

GitHub's web form sends `\r\n`. My tests wrote `\n`, and passed. So I wrote the CRLF version of the
same comment into the test, and broke the code by removing the normalisation:

```text
== don't normalise CRLF
E   quantic_agent.daily.NotRead: not "posted SYMBOL" or "posted SYMBOL version N" on the first
    line, then the text in a ```text block, and nothing after it
FAILED tests/test_daily.py::test_a_comment_records_a_post_a_review_or_nothing
```

Without that line, every comment I wrote in the browser would have been "not in the form". The
fake GitHub sends CRLF in the end-to-end test too, so this is checked in both places.

## A list is not an object

GitHub's comments endpoint answers with a JSON *list*. The client's `_validated` takes a Pydantic
`BaseModel`, and a model is an object with fields. My first version looped over the list and
validated each element, and strict pyright needed two `# pyright: ignore` because `found` was
`Any`. Pydantic's answer is `RootModel[list[IssueComment]]`: a model whose whole value is the
list, with `.root` to get it back. `_validated` works on it unchanged and the ignores went. In Go,
`json.Unmarshal(body, &[]IssueComment{})` does this without a wrapper type; Pydantic needs one
because validation is on classes.

The same method pages: 100 comments a request until a page comes back short. The fake GitHub
honours `per_page` and `page`, and a test with 150 comments checks it asks for two pages, not
three.

## "Once more", as a NULL

An open issue's comments are read on every sync. A closed one's should be read once more (I often
comment and close within a minute), then never again. That's migration 0007's trick:
`issues.comments_read_at`, NULL meaning *not read since it closed*. `record_comments(…,
closed=True)` sets it in the same transaction as the comments, so an issue is never marked read
with half of them.

The NULL also did the backfill for free. Every issue closed before this migration has NULL, so the
first sync reads them all. I ran this branch's `--sync` against a copy of my real database:

```text
run 8: the review, read: https://github.com/fleveque/quantic/issues/515#issuecomment-6491157252
run 9: the review, read: https://github.com/fleveque/quantic/issues/532#issuecomment-6517885726
run 12: the review, read: https://github.com/fleveque/quantic/issues/540#issuecomment-6599550493
run 13: the review, read: https://github.com/fleveque/quantic/issues/542#issuecomment-6628124849
```

and a second sync printed `no open pull requests or issues`, with no request to GitHub. Breaking
it (never setting `comments_read_at`) fails the end-to-end test where a comment added after the
final read must not be seen:

```text
E   assert 'run 1: comme...ment-200006\n' == 'no open pull...s or issues\n'
```

The cost is a rule for me: the `posted` comment goes in before I close, or at least before the next
sync, which on weekdays is the 07:30 timer.

## An edit replaces, a delete keeps

One row per GitHub comment id, written with SQLite's `INSERT … ON CONFLICT (comment_id) DO
UPDATE`. That's Rails' `upsert` and Ecto's `on_conflict: :replace_all`. An edited comment has a
new `updated_at`, so its row is replaced and `--sync` prints it again; an unchanged one is skipped
before the write. A comment I delete stays, as milestone 14's corrections stay: the store is the
record of what was read, not a mirror.

## Versions must exist

`posted NKE version 9` on an issue with three Nike versions is a typo too, and `--sync` names it
instead of keeping a post that points at nothing. Breaking that check showed the test catching it:
the line it expected never appeared.

## What `--run N` shows

A post from a version is shown as a word diff against the version *as the issue showed it*, the
text and the link, because that's what I copied. On the end-to-end test's edit:

```text
👟 [-Mostly-]{+Mostly,+} because the share price fell.
```

A post written from scratch is shown whole, and so is the review.

## What's next

Nothing reads these back yet. That was my choice: capture first, as with milestone 14, and pick
the first use once there are a few weeks of posts and reviews to measure it against. The
candidates are the posted texts as examples for the writer (milestone 10's style memory, but with
what I actually put my name to), new checks read out of the reviews (milestone 15's method), and
the repeat window counting what was posted instead of what was proposed.
