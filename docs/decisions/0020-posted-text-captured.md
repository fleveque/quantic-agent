# 0020 — What was posted on X, captured from the issue

**Status:** proposed · **Date:** 2026-10-29

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

## Proposal

**Capture first, as milestone 14 did; uses later, each the author's to choose.**

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
4. **Migration 0010**: `posts` (run, symbol, version nullable, text, comment id, read at) and
   `reviews` (run, comment id, text, read at). `--run N` shows each posted text as a word diff
   against its version (`difflib`, as for corrections), or whole when it has none.

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

## Open questions for the author

1. A comment per post (proposed), or the posted text pasted under the tick in the issue's body?
2. Store the review (proposed), or only the posts?
3. Which use first, if any: examples for the writer, or checks from the reviews?
