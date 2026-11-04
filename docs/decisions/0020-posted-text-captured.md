# 0020 — What was posted on X, captured from the issue

**Status:** accepted · **Date:** 2026-10-29, accepted 2026-11-04 (milestone 18)

## Context

A daily issue (decision 0019) records which versions the author ticked as posted, and whether the
issue is closed. `--sync` reads the ticks into `proposals.posted_at`. Nothing else comes back:

- **The text posted isn't recorded.** On quantic#515, the first real issue, the review recommended
  posting Realty Income's and Nike's versions with small edits, and Hitachi's rewritten from
  Hitachi's own release: Quantic's "annual rate" of 64 JPY was the raised interim dividend (32 yen)
  times two. A tick says "version 2 was posted"; what went out on X is in nobody's record but X's.
  That breaks design N3 (full auditability) for the one step the agent doesn't do.
- **The review isn't recorded.** Its verdicts ("v1: 'a jump from its average' implies the yield
  moved from it", "the streak is over 31 years, not 28") are the best evidence of what the writer
  and Quantic's data get wrong. They exist only as an issue comment.
- **Nothing uses what was posted.** The 7-day repeat window counts what was proposed (0019). The
  writer is shown no past posts.

Milestone 14 solved the same problem for the Week Ahead (decision 0016): `--sync` reads what the
merge published and stores each section that differs from the draft. This proposes the same for
the daily posts.

## Decision

**Capture first, as milestone 14 did; uses later, each the author's to choose.** The author
answered the open questions on 2026-11-04 (below), after quantic#542: its Brown-Forman post went out
edited from version 2, and nothing but the review on GitHub recorded what it said.

1. **The author records a post in a comment on the issue**, in a fixed form:

   ````text
   posted NKE version 3

   ```text
   💰 Nike ($NKE) yields 4.41% against a 1.41% 5-year average, mostly because …
   ```
   ````

   `posted SYMBOL version N` for an edited version, `posted SYMBOL` for one written from scratch, then
   the text as posted, in a `text` block. The tick stays the short way to say "posted as written".
   - **A comment, not an edit of the issue's body.** The body is the agent's record of what it
     proposed (`--run N` re-checks it). Pasting the posted text over a version would replace it.
     A comment keeps both. It also fits a post that started from no version (Hitachi's).
   - **Recognised by its first line, not its author.** The review is posted from the author's
     account too (`gh` is signed in as them), so authorship can't tell a review from a post.
2. **`--sync` reads the comments** of each daily issue it reads ticks for (GET
   `/repos/{repo}/issues/{n}/comments`; the App has Issues: read). For each comment in that form it
   stores the symbol, the version (or none), the posted text, the comment's id and its time. An
   edited comment is stored again; a deleted one is kept, as `corrections` keeps what it read. A
   closed issue is read once more, then no more.
3. **The review is stored too**: a comment starting `## Review (Claude)` (the `review-posts` form),
   whole, as text. Its structure is for people; storing it keeps the evidence without parsing it.
4. **Migration 0010**: one table, `issue_comments` (run, GitHub's comment id, url, kind `posted`
   or `review`, symbol and version for a post, text, GitHub's edit time, read at), and
   `issues.comments_read_at`. `--run N` shows each posted text as a word diff against its version
   as the issue showed it (text and link; `corrections.word_diff`), or whole when it has none.

### As built

- **One table, not `posts` and `reviews`**: both names were taken (the Week Ahead's posts,
  milestone 11; the verdicts, milestone 10), and a post and a review differ by two nullable
  columns.
- **"Read once more" is `comments_read_at`**: an open issue's comments are read on every sync; a
  closed one's once after closing, which sets it. NULL on a closed issue means not read since it
  closed, as a NULL `merge_commit` did in migration 0007, so the first sync after the migration read
  the issues closed before it: on a copy of the real database, the reviews on quantic#515, #532,
  #540 and #542. A comment added after that read isn't seen: post the `posted` comment before
  closing the issue, or before the next sync.
- **A version must be one the issue proposed**: `posted NKE version 9` is named and not kept, like
  a comment not in the form (`daily.NotRead`). `posted SYMBOL` with no version is any company.
- The first line is read case-insensitively and CRLF (the web form's) as LF; the symbol is kept in
  capitals.

The client gains one GET (`issue_comments`); it still has no method that writes a comment, edits or
closes an issue.

## What it could then be used for (not proposed now)

- **Examples for the writer**: the nearest posted texts, as milestone 10's style memory shows the
  writer approved answers. Posted texts are better examples than ticked versions: they're what the
  author was willing to put their name to.
- **New checks from the reviews**, by reading them, as milestone 15's wording rules came from
  reading real writings: "a jump from its average", "sits" for a last known price.
- **The repeat window from what was posted**, so a company proposed and not posted can come back
  sooner.
- **Data issues for Quantic** from the reviews' "For Quantic's data" sections.

## Consequences, if accepted

- The author pastes each post once more after posting it. A post not pasted is only its tick, as
  today.
- A comment in a slightly different form isn't read. `--sync` can say which comments it skipped
  that start with "posted", so a typo doesn't go unnoticed.
- The posted texts are the author's writing, stored locally like the rest of the store (N4: nothing
  leaves the machine that didn't already).

## The author's answers (2026-11-04)

1. **A comment per post**, not the text pasted under the tick.
2. **Store the review too**, whole.
3. **Capture now, use next**: no use in this milestone. Examples for the writer or checks from the
   reviews come after, once there are posts and reviews to measure them against.
