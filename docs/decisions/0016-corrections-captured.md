# 0016 — The reviewer's corrections, read back from the merge commit

**Status:** accepted · **Date:** 2026-10-14

## Context

`--sync` recorded only whether a pull request was merged (decision 0014). On quantic#492, the first
Week Ahead published, a review corrected six of the seven locales on the branch before the merge:
Catalan "divisió" for dividend and "per davant" (ahead) for behind, Italian "dello stesso periodo"
for "in the same week", Portuguese "lucros" (profits) for results, and rewordings in Spanish,
French and German. The store kept the 27B's drafts and called the run approved. The corrections, the
only evidence of what the translations get wrong, existed only in Quantic's git history, and the
run's stored posts were no longer what had been published (design N3).

Three uses were put to the author: capture the corrections; a per-locale glossary with a check that
holds a known-wrong term; past corrections retrieved as examples for the translator (design §3.4's
retrieval, for Week Aheads). The last two need the first.

## Decision

The author chose **capture only**, for now. When `--sync` sees a merged pull request, it reads each
file the pull request proposed back from the **merge commit** and compares it with the post the
agent stored, **section by section**: each prose section by its key, the data block as data, the
rest of the frontmatter together. Each section that differs is stored with the text the agent wrote
and the text published (migration 0007, `corrections`). A file the reviewer left out is a
correction of the whole file with nothing published; a file that no longer reads back as a post is
stored whole. The pull request records the merge commit it was read at, in the same transaction.

- **The merge commit, not `main`.** With a squash merge, `merge_commit_sha` is the one commit `main`
  gained, so its files are exactly what the merge published. `main` may have changed since.
- **Read once, retried until it is.** A merged pull request without a merge commit recorded hasn't
  been read: every sync reads those, whenever they were merged. That reads quantic#492, merged
  before this version, on the first sync after installing it, and retries a read that failed.
- **Sections, not lines.** A post's prose section is one paragraph on one line, so a line diff
  says "the paragraph changed". The section is the unit the writer and the translator produce, and
  the unit a glossary check or a retrieved example would use. `--run N` shows each one as a word
  diff (`[-removed-]{+added+}`), computed when it's shown. The stored texts are the record.
- **Read through the contents API, GET only.** The client gains `file(path, ref)`; it still has no
  method that writes a file, updates a ref or merges.

## Consequences

- On the real quantic#492 the first sync found 8 corrected sections in 6 locales, English
  unchanged, in about 4 seconds. A second sync asked GitHub nothing.
- The drafts stay as written. What was published is in `corrections`. The run's posts are
  never rewritten.
- Nothing yet uses the corrections: the next Week Ahead is written exactly as before. A glossary
  check and retrieval for the translator are the next options (CLAUDE.md "Next").
- The paths read are the ones `--pr` would compute now (`--repo-path`, the run's week). Changing
  `--repo-path` between opening a pull request and syncing it would read the wrong place and record
  every file as left out.
- A locale the reviewer added on the branch isn't read: only the files the pull request proposed
  are compared.
- `difflib`'s matching isn't git's. It finds the longest common runs first, not the fewest edits,
  so for the same pair of texts its word diff can mark different, equally correct changes. It
  affects how a diff is shown, never what is stored.
