"""The week's X post, drafted by code from the Week Ahead's data (ADR 0018).

The agent never posts it: the draft goes in the pull request's description,
and the author copies it, edits it if they like, and posts it. Code writes
it, not the model, from a fixed template, so every figure in it is the data
block's (a percentage is worked out from a change's two rates, as the page
does) and it reads the same each week: the week's dates; how many companies go
ex-dividend, with the cashtags of the two US listings with the longest raise
streaks; the two biggest raises and the biggest cut of 1% or more; how many
companies report; the link to the post; two hashtags.

X counts a link as 23 characters and an emoji or a CJK character as two, and
refuses a post over 280. x_length counts the same way, and draft drops lines
in a fixed order until the post fits.
"""

import re
from datetime import date

from quantic_agent.weekahead import DividendChange, Week, WeekData

LIMIT = 280
SITE = "quantic.finance"
HASHTAGS = "#DividendInvesting #Dividends"

# X turns $ABC into a cashtag for US-style tickers only: $ITX.MC isn't one.
_CASHTAG = re.compile(r"[A-Z]{1,5}")
# A change under 1% is mostly a listing's rate moving with the exchange rate
# (quantic#509), so the post names only larger ones.
MIN_CHANGE = 0.01
_URL_WEIGHT = 23
# twitter-text's ranges that weigh 1; every other code point weighs 2.
_LIGHT = ((0x0000, 0x10FF), (0x2000, 0x200D), (0x2010, 0x201F), (0x2032, 0x2037))


def cashtag(symbol: str) -> str | None:
    """The ticker as X links it, "$NKE", or None for one X doesn't."""
    return f"${symbol}" if _CASHTAG.fullmatch(symbol) else None


def x_length(text: str, urls: tuple[str, ...] = ()) -> int:
    """A post's length as X counts it: each link 23, each character 1 or 2."""
    for url in urls:
        text = text.replace(url, "")
    weight = sum(1 if any(lo <= ord(c) <= hi for lo, hi in _LIGHT) else 2 for c in text)
    return weight + _URL_WEIGHT * len(urls)


def draft(week: Week, data: WeekData) -> str:
    """The post for week, from its data. Lines are dropped in this order until
    it fits: the earnings count, the cut, the raises, the hashtags."""
    url = f"{SITE}/insights/{week.path}"
    header = f"Dividend Week Ahead, {_day(week.start)} \N{EN DASH} {_day(week.end)}:"
    droppable = {
        "earnings": _earnings_line(data),
        "cut": _cut_line(data.dividend_changes),
        "raises": _raises_line(data.dividend_changes),
        "hashtags": HASHTAGS,
    }

    def compose() -> str:
        facts = [
            line
            for line in (
                _ex_dividend_line(data),
                droppable["raises"],
                droppable["cut"],
                droppable["earnings"],
            )
            if line
        ]
        tail = [line for line in ("", droppable["hashtags"]) if droppable["hashtags"]]
        return "\n".join([header, "", *facts, "", "Day by day, with safety reads 👇", url, *tail])

    text = compose()
    for key in ("earnings", "cut", "raises", "hashtags"):
        if x_length(text, (url,)) <= LIMIT:
            break
        droppable[key] = ""
        text = compose()
    return text


def _day(day: date) -> str:
    return f"{day:%b} {day.day}"


def _ex_dividend_line(data: WeekData) -> str:
    rows = data.ex_dividends
    if not rows:
        return "📅 No company goes ex-dividend"
    noun, verb = ("company", "goes") if len(rows) == 1 else ("companies", "go")
    line = f"📅 {len(rows)} {noun} {verb} ex-dividend"
    # The longest raise streaks first: the names dividend investors follow.
    tagged: list[str] = []
    for row in sorted(rows, key=lambda r: r.streak_years or 0, reverse=True):
        tag = cashtag(row.symbol)
        if tag is not None and tag not in tagged:
            tagged.append(tag)
        if len(tagged) == 2:
            break
    return f"{line}, incl. {' and '.join(tagged)}" if tagged else line


def _change(row: DividendChange) -> float:
    return row.new_rate / row.old_rate - 1


def _raises_line(changes: list[DividendChange]) -> str:
    raises = sorted((c for c in changes if _change(c) >= MIN_CHANGE), key=_change, reverse=True)
    if not raises:
        return ""
    named = ", ".join(f"{_stock(c)} {_change(c):+.0%}" for c in raises[:2])
    return f"📈 Recent raise{'s' if len(raises[:2]) > 1 else ''}: {named}"


def _cut_line(changes: list[DividendChange]) -> str:
    cuts = sorted((c for c in changes if _change(c) <= -MIN_CHANGE), key=_change)
    if not cuts:
        return ""
    return f"📉 {_stock(cuts[0])} cut its dividend {-_change(cuts[0]):.0%}"


def _earnings_line(data: WeekData) -> str:
    count = len(data.earnings)
    if not count:
        return ""
    return f"📊 {count} earnings report{'' if count == 1 else 's'}"


def _stock(row: DividendChange) -> str:
    """A cashtag where X makes one, else the company's name, in title case
    when the provider wrote it in capitals ("PAX GLOBAL")."""
    if (tag := cashtag(row.symbol)) is not None:
        return tag
    name = row.name.strip()
    return name.title() if name.isupper() else name
