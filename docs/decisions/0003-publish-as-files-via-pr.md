# 0003 — Publish as files through a PR, not through a drafts API

**Status:** accepted · **Date:** 2026-09-10 · **Revisit at:** ~2,000 posts, or the first time a
publish needs to happen without a deploy

## Context

The agent commits post files to the Quantic repo and opens a PR. The alternative: Quantic exposes a
drafts API, the agent POSTs structured drafts into a `posts` table, and an admin screen handles
review and publication.

The concern raised, fairly: files and PRs feel like they won't scale as post count and traffic grow.

## The two "scale" questions are different

**Reader traffic — files win, and not narrowly.** NimblePublisher compiles posts at build time into
in-memory structs. Serving a post is a struct lookup: no query, no N+1, no cache layer, no cache
invalidation. A DB-backed post costs a query per request until a cache is built, and then costs a
cache to maintain. At 1k or 1M pageviews the file version is the same flat cost. This is the axis the
concern was really about, and it points the other way.

**Post volume — files have a ceiling, but it's far away.** Compile-time loading means every post is
parsed at build. At weekly cadence across 7 locales that's 364 files a year. Even at 10 years and
several formats it's a few thousand files — parsed once per deploy, not per request. It would take a
long time to become uncomfortable, and high volume is an explicit anti-goal (Google's
scaled-content-abuse policy, see the [content plan](../content.md)).

**Editorial volume — 52 PRs a year, opened automatically.** Not a bottleneck.

## Decision

Files, committed by the agent, published through a PR.

Note the drafting stage is *already* database-backed: drafts live in the agent's local SQLite with a
`pending_review` state, and only an approved draft becomes a commit. The PR is the **publication**
step, not the drafting step. What's being compared is *where published content lives*, not whether a
database is involved at all.

## Why

**Review is the product, and a PR diff is the best review UI in existence.** The entire design is
human-in-the-loop. GitHub gives line comments, suggested edits, history, blame and revert for free.
Building an equivalent admin review screen inside Quantic is real work that buys nothing the PR
already does better.

**Auditability (N3) comes free.** Every published figure has a commit, a diff, a timestamp and an
author. Reconstructing what was published and when is `git log`, not a schema for it.

**Approve and publish become one action.** Merging to `main` already deploys. There's no
half-published state, no "approved but not live", no second button to forget.

**No new write surface on production.** A drafts API means an authenticated write endpoint reachable
from an external daemon, a migration, and an admin UI — attack surface and work in the private repo,
for a workflow that git already implements.

**Content is versioned alongside the template that renders it.** A format change and the posts using
it land together, and roll back together.

## Consequences

**Publishing requires a deploy.** This is the real cost. A typo fix at 11pm means a deploy rather than
an edit. Kamal deploys are fast, so it's an inconvenience rather than a problem — but it is the
genuine downside, and the first time it actually hurts is the signal to revisit.

**Scheduled publishing needs a small convention** rather than a `publish_at` query. Posts carry
`published_at`; the index filters to posts at or before now. Merging early is safe, the post simply
isn't listed until its date.

**No non-technical editing.** Editing a post means editing a file in git. Fine for a single-author
project; a blocker the day someone else writes for Quantic.

## Why this is a cheap decision to get wrong

Because of [ADR 0002](0002-structured-data-not-markdown-prose.md), a post is already typed structured
data. Migrating to a database later is `yaml.Unmarshal` into an insert, and the rendering templates
don't change at all — they consume a `Post` struct either way, regardless of whether it came from a
file or a row.

The format decision is the one that was expensive to get right. Storage is swappable behind it, which
is exactly why it was worth spending the care there instead of here.
