# 0014 — Pull requests as a GitHub App, a client that can't touch main, and merges as verdicts

**Status:** accepted · **Date:** 2026-10-08

## Context

[Decision 0003](0003-publish-as-files-via-pr.md) publishes posts as files through a pull request on
Quantic's repository, and design §3.8 relies on `main` being "protected independently, so a bug in
the agent cannot merge". Milestone 11 writes the files; milestone 12 opens the pull requests.

Checked on 2026-10-08: Quantic's repository is private, and on its owner's plan GitHub refuses both
branch protection and rulesets for private repositories ("Upgrade to GitHub Pro or make this
repository public", 403). Pushing a branch needs Contents write, and that permission covers `main`.
Merging to `main` deploys to production.

## Decision

The author chose, from options put to them: a GitHub App; pull requests on the Quantic repository
now; every ready locale in the pull request, with no locale published on machine checks alone; a
command that records merges and closes as verdicts; and, for `main`, the agent's own guard plus a
deploy-side check rather than a paid plan or a sandbox repository.

1. **A GitHub App**, installed on the Quantic repository only, with Contents and Pull requests
   write. The agent signs a JWT with the App's private key and exchanges it for an installation
   token that lasts an hour. Pull requests appear as the App's bot, not as a person, and no
   person's token is involved: decision 0006's rule, applied to GitHub. The key is a file only its
   owner can read; the agent refuses one that others can.
2. **A client that can't change an existing branch** (`github.py`). Its only write to a ref is
   creating one, which GitHub refuses when the ref exists, as `main` always does. The branch must be
   under `agent/`, checked before any request. It has no method that updates or deletes a ref,
   merges, or writes through the contents API. Tests check every request a pull request makes.
3. **Quantic's deploy refuses a bot's push to `main`** (quantic#486): a change to the agent that
   broke rule 2 would land in `main` but not deploy.
4. **`--pr N` opens one pull request per Week Ahead run**, from the run's posts as stored: one
   commit with every ready locale under `priv/insights/<slug>/` (`--repo-path`), on
   `agent/<slug>-run-N`. Held locales stay out and are listed. The description says that merging
   publishes, what was checked, and that the translation checks don't read the language. A week
   with a pull request open can't have a second until `--sync` has seen the first decided.
5. **`--sync` reads back each open pull request.** A merge records the run as approved, a close
   without merging as rejected (the accept rate of design open question 3). Week Ahead verdicts
   don't become style memory.

## Consequences

- N2 rests on the agent's code and on the deploy workflow, not on GitHub. A bot push to `main`
  would still change `main`, undeployed, until someone noticed. GitHub Pro (protection for private
  repositories) would make GitHub enforce it, and is the change to make if this ever matters more.
- Nothing renders `priv/insights/` yet. Until `/insights` exists, merging a pull request ships
  files nothing reads; closing it is a rejection.
- The App must be created by hand ([runbook §8b](../target-machine.md#8b-pull-requests)): its ID and
  private key are configuration, never in the repository.
- New dependency: PyJWT, with `cryptography` for RS256.
- Approving through the merge means the reviewer can edit or delete files on the branch before
  merging; the run's record keeps what the agent proposed, and the merge commit what was published.
