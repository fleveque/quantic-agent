"""A Week Ahead run as a pull request (milestone 12): the branch, the files,
and what the description tells the reviewer.

Everything comes from the run as stored, not from the folder --week-ahead
wrote: what goes for review is exactly what was checked and recorded.
"""

from dataclasses import dataclass

from quantic_agent import github, store, weekahead


class NotPublishableError(Exception):
    """The run can't become a pull request. The message says why."""


@dataclass(frozen=True)
class Proposal:
    """A pull request about to be opened."""

    period: str
    branch: str
    files: list[github.File]
    message: str  # the commit's
    title: str
    body: str


def proposal(run: store.Run, repo_path: str) -> Proposal:
    """The pull request for a Week Ahead run: its ready locales' files under
    repo_path/<ISO year>/<slug>/, on a branch of its own. Held locales stay
    out, and the description says why."""
    if run.kind != weekahead.KIND:
        raise NotPublishableError(f"run {run.id} is a {run.kind}: only a Week Ahead is published")
    if run.state is not store.State.ANSWERED:
        raise NotPublishableError(
            f"run {run.id} is {run.state}: only a post that passed its checks is published"
        )
    ready = [p for p in run.posts if p.ready]
    if not any(p.locale == weekahead.SOURCE for p in ready):
        raise NotPublishableError(f"run {run.id} has no English post")
    week = weekahead.week_of(run)
    files = [github.File(path, p.content) for p, path in locations(run, repo_path)]
    locales = ", ".join(p.locale for p in ready)
    return Proposal(
        period=week.period,
        branch=f"{github.BRANCH_PREFIX}week-ahead-{week.period}-run-{run.id}",
        files=files,
        message=f"Dividend Week Ahead {week.period}, from quantic-agent run {run.id}\n\n"
        f"Locales: {locales}.",
        title=f"Dividend Week Ahead, {week.period}",
        body=_body(run, week, files),
    )


def locations(run: store.Run, repo_path: str) -> list[tuple[store.Post, str]]:
    """Each ready post of a run, with its file's path in the repository:
    repo_path/<ISO year>/<slug>/<locale>.md. Where the pull request put
    them, and where --sync reads them back from once it's merged."""
    week = weekahead.week_of(run)
    folder = f"{repo_path.strip('/')}/{week.path}"
    return [(p, f"{folder}/{p.locale}.md") for p in run.posts if p.ready]


def _body(run: store.Run, week: weekahead.Week, files: list[github.File]) -> str:
    english = next(p for p in run.posts if p.locale == weekahead.SOURCE)
    front, _ = weekahead.read_back(english.content, weekahead.SOURCE)
    data = front["data"]
    companies = "\n".join(
        f"- {row['name']} ({row['symbol']}), ex-dividend {row['ex_dividend_date']}"
        for row in data["ex_dividends"]
    )
    rows = "\n".join(
        f"| {f.path.rsplit('/', 1)[1].removesuffix('.md')} | `{f.path}` |" for f in files
    )
    held = [p for p in run.posts if not p.ready]
    held_lines = "\n".join(f"- **{p.locale}**: {'; '.join(p.problems)}" for p in held)
    held_section = f"\n**Held back, not in this pull request:**\n\n{held_lines}\n" if held else ""
    return f"""\
The Dividend Week Ahead for Monday {week.start} to Sunday {week.end}, written by \
quantic-agent (run {run.id}, `{run.model}`).

**Merging publishes it.** Delete a locale's file from this branch to leave that locale \
out, or close the pull request to reject the post.

**What the agent checked**

- Every figure is in the `data` block, copied by code from Quantic's tool results and \
checked against them. The block is the same in every file.
- The prose has no figures, in digits or in English words.
- Each translation has no figures and a length near the English's. These checks don't \
read the language: a translation can pass them and still be wrong. No one has read any \
of them.

**What it can't check:** whether a sentence with no figure in it is true, and whether \
it leans towards advice. That is this review.

| Locale | File |
|---|---|
{rows}
{held_section}
**The week's companies**

{companies}

**Also in the data block:** {len(data["earnings"])} earnings report(s) in the week, \
{len(data["dividend_changes"])} dividend raise(s) or cut(s) seen in the last \
{weekahead.CHANGES_DAYS} days.

`quantic-agent --run {run.id}` shows the tool calls behind it, on the machine that wrote it.
"""
