# Lesson 12 — A merge is a verdict

**Milestone 12** — a Week Ahead run becomes a pull request on Quantic's repository, opened by a
GitHub App, and the agent learns what became of it: merged is approved, closed is rejected. The agent
still publishes nothing. It proposes, and I decide in the place I already review code. Building it, I
found that the protection the design counted on doesn't exist for Quantic, and a Friday showed that
milestone 11's fix for the date was only half a fix.

*Also readable as a [formatted page](https://claude.ai/artifact/6rVThLvzeZV4REpF9v3ssU), with a [code walkthrough](https://claude.ai/artifact/G4oMqWLNDdTnkheWyzCysZ) of every change the
milestone made.*

---

## What I chose

Four decisions, before any code. The agent opens pull requests as a **GitHub App**, never with my
personal token: decision 0006 already said the agent gets no personal access token, and a token that
can do everything I can is the clearest case of it. The pull requests go to **Quantic's repository
now**, under `priv/insights/`, though nothing renders that folder yet. **Every ready locale** goes in
one pull request, and I review them all. And a **sync command** asks GitHub what happened to each
one, rather than a webhook: the agent runs on my machine and nothing on the internet can reach it.

## The protection that wasn't there

The design's safety argument was: the agent can only open pull requests, `main` is protected, so
only I can publish. Then I asked GitHub to protect Quantic's `main`:

```
gh: Upgrade to GitHub Pro or make this repository public to enable this feature. (HTTP 403)
```

Branch protection and rulesets aren't available for a private repository on the free plan. And a
GitHub App's "Contents: write" covers every branch, `main` included. Nothing on GitHub's side would
stop a bug from pushing to `main`, and Quantic deploys on every push to `main`.

I chose two guards instead. The first is the client itself. The only write it makes to a ref is
*creating* one, and GitHub refuses to create a ref that exists, so `main` can't be written by it.
There is no method that updates, deletes, force-pushes or merges, and branches must start with
`agent/`, checked before any request. On the real repository, as the App:

```
POST /repos/fleveque/quantic/git/refs {"ref": "refs/heads/main", ...}
422 Reference already exists
```

The second is in Quantic: its deploy workflow now fails as its first step if a bot pushed to `main`
or started the run (quantic#486). My own merge, the deploy after it showed, skips that step and goes
ahead. A change to the agent that broke the first rule still wouldn't deploy.

## Who the App is

An App proves who it is with a private key I downloaded once. It signs a short JWT with it:

```python
claims = {"iat": issued, "exp": issued + 600, "iss": app_id}
token = jwt.encode(claims, private_key, algorithm="RS256")
```

That JWT is good for one thing: asking for an installation token, which lasts an hour and works only
on the repositories the App is installed on, with the permissions I gave it. Everything else uses
that token. The client fetches it on first use and again a minute before it expires. PyJWT does the
signing; in Go it would be `golang-jwt/jwt`, in Elixir `Joken`, in Ruby the `jwt` gem, and Octokit
has a method for each step. I wrote the exchange myself because it's two requests, and I wanted
to see which credential goes where. The test checks that the JWT is sent exactly once.

The key file is refused unless only I can read it, as `ssh` refuses a private key others can:

```python
if path.stat().st_mode & 0o077:
    raise SettingsError(f"{path} is readable by others: chmod 600 {path}")
```

`0o077` is Python's octal literal; Go and Elixir write it the same way. The
mask is the group and others bits: any of them set and the key isn't private.

## One commit in five requests

GitHub's contents API writes one file per commit. Seven locales would be seven commits, and the
branch would exist, half-written, after the first. The Git Data API builds a commit the way git
itself does: read the base branch's head, read its commit for the tree, make a new tree with the
seven files on top of it, make a commit of that tree, and only then create the branch pointing at
it. Until that last step nothing is visible, so a failure leaves only objects nobody references,
which GitHub cleans up.

## A merge is a verdict

`--sync` looks at every pull request the agent last saw open. Merged, it records the run as
approved; closed, as rejected, with a note saying which pull request. Both writes happen in one
transaction, so the pull request's state and the verdict never disagree. That's design open question
3's accept rate, counted from what I actually do instead of a command I'd have to remember.

There is at most one pull request per run (`UNIQUE` in the table) and one open per week, checked
before asking GitHub. A second run for the same week waits until I've decided on the first.

## The first real one

I created the App, installed it on Quantic only, and the agent opened
[quantic#487](https://github.com/fleveque/quantic/pull/487): author `app/quantic-agent-fleveque`,
one commit by `quantic-agent-fleveque[bot]` on `agent/week-ahead-2026-W42-run-3`, seven files.
Reading it was the point of the exercise. The English said Procter & Gamble's "recent earnings
acceleration … outpaces the broader long-term trend": its recent dividend growth is 4.0% against
6.0% over five years, and it's dividends, not earnings. No figure in that sentence, so no check
could catch it. The Catalan began "Aquesta set". I closed it, and:

```
$ quantic-agent --sync
run 3: https://github.com/fleveque/quantic/pull/487 closed: rejected
```

## It was a Friday

The first run of the day failed in research. The model had been told "Today is Friday 2026-10-09"
and the week's dates, and asked the calendar for 7 days anyway. From a Friday that ends on the
Friday before the week's Sunday. Milestone 11's twenty successes were all on a Thursday. `--resume`
replayed the same calls and stopped at the same place: asking again doesn't change the model's mind.
Told the date, it still had to count, and it counted to its habit. The question now does the
arithmetic for it, "Sunday 2026-10-18 is 9 days from today", and five runs of five then asked for
nine days.

The same five runs found something else. Three of them wrote "two" in the prose three times running,
and nothing was written. Yesterday the same prompt on the same data published nineteen times in
twenty. I don't know yet why, and how to fix it is my decision: the prompt says "two" itself twice.

## What I'm taking into milestone 13

- A design's guarantee is a claim about someone else's system. Check it there, early.
- When the platform won't enforce a rule, write the client so it can't break it, then guard the next
  step too.
- A credential that can do one thing, for an hour, on one repository, is the right size for an agent.
- One commit for one change: build the tree, then point a branch at it.
- Record decisions where they're made. A merge is already a review.
- Don't make the model count. Give it the number.

---

**Previous:** [Lesson 11 — Seven files, one set of figures](11-seven-files-one-set-of-figures.md)
