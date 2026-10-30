"""The daily X posts (milestone 16, decision 0019): a few companies a weekday,
each drafted in a few versions for the author to pick from and post.

Measured first (docs/benchmarks/2026-10-28-x-posts/): the model is good at
choosing among facts and writing them up, and poor at finding them. So code
does everything up to the writing:

- gathers the day's data, recorded with the run like any tool call: the
  recent raises and cuts, the coming ex-dividends, and one screen of safe
  companies with a long streak (first_calls);
- chooses up to one company per angle (a dividend change, an ex-dividend,
  a yield against its own history), skipping any proposed in the last
  REPEAT_DAYS, and looks each up with get_stock until one is accepted
  (candidates, look_up, accepts);
- computes the facts the writer may use (facts): values copied from the
  tools, checked against them like any data, and values code worked out
  from those, such as the size of a raise or why a yield is high. A cause
  the model isn't given as a fact, it gets wrong.

The model then writes a few versions of one post per company, each checked
(check_version) and sent back with what's wrong, as the Week Ahead's prose
is. The versions that pass go into one GitHub issue a day (issue_body),
which the author reviews, posts from, and ticks (ticks): the agent posts
nothing (design N2).
"""

import json
import re
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from importlib import resources
from string import Template
from typing import Any

from pydantic import BaseModel, ValidationError

from quantic_agent import agent, llm, provenance, wording, xpost
from quantic_agent.agent import Call, Model
from quantic_agent.tools import (
    DIVIDEND_CALENDAR,
    DIVIDEND_CHANGES,
    GET_STOCK,
    SCREEN_STOCKS,
    Tool,
)

KIND = "daily_posts"  # its runs' kind in the store

# How many companies a day can bring: one per angle.
LOOKUPS = 6  # get_stock calls at most per angle, until one company is accepted
CHANGES_DAYS = 3  # raises and cuts seen in the last three days: Monday sees the weekend's
CALENDAR_DAYS = 5  # from a Friday, the next two weekdays are Monday and Tuesday
EX_DIVIDEND_WEEKDAYS = 2  # ex-dividends in the next two weekdays
REPEAT_DAYS = 7  # a company proposed in this many days isn't proposed again
MIN_STREAK = 10  # the screen's, and an ex-dividend's
MIN_RAISE_STREAK = 5  # a raise from a shorter record is mostly a first payment or noise
MIN_YIELD_RATIO = 1.25  # a yield this many times its own 5-year average, or more
MAX_EX_DIVIDEND_YIELD = 8.0  # higher is mostly a fund or a trap, not a story to tell
# Secondary listings of companies listed elsewhere: their rate moves with the
# exchange rate, and the company has a primary listing with its own data.
SECONDARY = (".F", ".DE", ".XC", ".MU", ".HA", ".BE", ".DU", ".SG", ".HM")

VERSIONS = 3  # a post's versions for the author to choose from
ATTEMPTS = 3
MAX_TEXT = 240  # characters of text before the link
EMOJI = "👟💰📈📉🔥🧾💵📊📅🔍"
SITE = f"https://{xpost.SITE}"

PROMPT = Template(
    resources.files("quantic_agent").joinpath("prompts", "daily_post.md").read_text("utf-8")
)
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class Angle(StrEnum):
    """What a post is about. One company per angle a day, in this order."""

    CHANGE = "change"  # a raise or a cut Quantic saw recently
    EX_DIVIDEND = "ex_dividend"  # going ex-dividend in the next weekdays
    YIELD = "yield"  # a yield well above the company's own 5-year average


# ---- what the tools return, read as far as the posts need --------------------


class _Change(BaseModel):
    symbol: str
    name: str | None = None
    old_rate: float
    new_rate: float
    currency: str | None = None
    detected_on: date
    # "payment": one payment against the same payment a year earlier, a
    # semi-annual payer's (quantic#517). Quantic before it sends none.
    basis: str = "annual"

    @property
    def ratio(self) -> float:
        return self.new_rate / self.old_rate - 1


class _Changes(BaseModel):
    changes: list[_Change]


class _Listed(BaseModel):
    symbol: str
    name: str
    ex_dividend_date: date
    pay_date: date | None = None
    dividend_rate: float | None = None
    currency: str | None = None
    dividend_yield: float | None = None  # a percentage: 5.74 for 5.74%


class _Calendar(BaseModel):
    stocks: list[_Listed]


class _Screened(BaseModel):
    symbol: str
    name: str
    instrument_type: str | None = None
    dividend_yield: float | None = None  # percentages
    yield_avg_5y: float | None = None

    @property
    def ratio(self) -> float:
        if not self.dividend_yield or not self.yield_avg_5y:
            return 0.0
        return self.dividend_yield / self.yield_avg_5y


class _Screen(BaseModel):
    results: list[_Screened]


class _Profile(BaseModel):
    symbol: str
    name: str
    currency: str | None = None
    sector: str | None = None
    payment_months: list[int] = []
    # "ex_dividend", or absent before quantic#533: payment_months are the months
    # the stock goes ex-dividend, and the cash may arrive later.
    payment_months_basis: str | None = None
    ex_months: list[int] = []
    payment_frequency: str | None = None


class _PriceHistory(BaseModel):
    high: float | None = None


class _History(BaseModel):
    price: _PriceHistory | None = None
    dividend_by_year: dict[str, float] = {}


class _Band(BaseModel):
    avg_5y: float | None = None
    high_5y: float | None = None


class _Safety(BaseModel):
    status: str | None = None


class _DividendProfile(BaseModel):
    safety: _Safety | None = None
    streak_years: int | None = None
    cagr_5y: float | None = None


class _LastPrice(BaseModel):
    price: float | None = None
    currency: str | None = None
    as_of: datetime | None = None


class Stock(BaseModel):
    """get_stock's reply, as far as a post uses it."""

    profile: _Profile
    history: _History | None = None
    yield_band: _Band | None = None
    dividend_profile: _DividendProfile | None = None
    last_known_price: _LastPrice | None = None

    @property
    def streak(self) -> int | None:
        return self.dividend_profile.streak_years if self.dividend_profile else None


class IncompleteError(Exception):
    """A tool's reply wasn't what the posts are built from."""


def _latest[M: BaseModel](calls: Sequence[Call], tool: str, model: type[M]) -> M | None:
    """The last successful call to tool, read as model; None if there was none."""
    for c in reversed(calls):
        if c.tool == tool and not c.failed:
            try:
                return model.model_validate_json(c.result)
            except ValidationError as err:
                raise IncompleteError(f"{tool} returned something unexpected: {err}") from err
    return None


# ---- gathering and choosing --------------------------------------------------


def first_calls() -> list[tuple[str, dict[str, Any]]]:
    """The calls every day starts with, made by code: the arguments follow
    from the day, so there is nothing for a model to decide."""
    return [
        (DIVIDEND_CHANGES.name, {"days": CHANGES_DAYS}),
        (DIVIDEND_CALENDAR.name, {"days": CALENDAR_DAYS}),
        (SCREEN_STOCKS.name, {"min_streak": MIN_STREAK, "safety": "safe", "type": "equity"}),
    ]


def next_weekdays(today: date, n: int) -> list[date]:
    """The n weekdays after today: from a Friday, Monday and Tuesday."""
    days: list[date] = []
    day = today
    while len(days) < n:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return days


@dataclass(frozen=True)
class Candidate:
    """A company that might be posted about, and the row that made it one."""

    angle: Angle
    symbol: str
    change: _Change | None = None
    listed: _Listed | None = None
    screened: _Screened | None = None


def candidates(
    calls: Sequence[Call], today: date, recent: set[str]
) -> dict[Angle, list[Candidate]]:
    """The companies worth looking up, best first, at most LOOKUPS per angle.
    Secondary listings are left out, and so is any company in recent (those
    proposed lately) or already a candidate for an earlier angle.

    - Changes: of 1% or more (xpost.MIN_CHANGE), the largest first.
    - Ex-dividends: in the next EX_DIVIDEND_WEEKDAYS weekdays, with a yield of
      at most MAX_EX_DIVIDEND_YIELD, the highest first.
    - Yields: from the screen, at least MIN_YIELD_RATIO times their own
      5-year average, the furthest above it first.
    """
    seen = set(recent)

    def keep(symbol: str) -> bool:
        if symbol in seen or symbol.endswith(SECONDARY):
            return False
        seen.add(symbol)
        return True

    out: dict[Angle, list[Candidate]] = {}
    changes = _latest(calls, DIVIDEND_CHANGES.name, _Changes)
    rows = sorted(
        (c for c in changes.changes if abs(c.ratio) >= xpost.MIN_CHANGE) if changes else (),
        key=lambda c: abs(c.ratio),
        reverse=True,
    )
    out[Angle.CHANGE] = [Candidate(Angle.CHANGE, c.symbol, change=c) for c in rows]
    calendar = _latest(calls, DIVIDEND_CALENDAR.name, _Calendar)
    days = set(next_weekdays(today, EX_DIVIDEND_WEEKDAYS))
    listed = sorted(
        (
            s
            for s in (calendar.stocks if calendar else ())
            if s.ex_dividend_date in days
            and s.dividend_yield is not None
            and s.dividend_yield <= MAX_EX_DIVIDEND_YIELD
        ),
        key=lambda s: s.dividend_yield or 0.0,
        reverse=True,
    )
    out[Angle.EX_DIVIDEND] = [Candidate(Angle.EX_DIVIDEND, s.symbol, listed=s) for s in listed]
    screen = _latest(calls, SCREEN_STOCKS.name, _Screen)
    screened = sorted(
        (
            r
            for r in (screen.results if screen else ())
            if r.instrument_type in (None, "equity") and r.ratio >= MIN_YIELD_RATIO
        ),
        key=lambda r: r.ratio,
        reverse=True,
    )
    out[Angle.YIELD] = [Candidate(Angle.YIELD, r.symbol, screened=r) for r in screened]
    # In angle order, so a company that is both a raise and a high yield is the raise.
    return {angle: [c for c in out[angle] if keep(c.symbol)][:LOOKUPS] for angle in Angle}


def accepts(candidate: Candidate, stock: Stock) -> str | None:
    """Why a candidate isn't posted about, once looked up; None if it is.

    The data's own contradictions are reasons: a cut next to a streak of
    increases that is still running (Intertek, 2026-10-28) is Quantic's data
    to fix, not a post."""
    streak = stock.streak
    match candidate.angle:
        case Angle.CHANGE:
            assert candidate.change is not None
            if candidate.change.ratio < 0 and streak:
                return (
                    f"a cut next to a running streak of {streak} years: the data contradicts itself"
                )
            if candidate.change.ratio > 0 and (streak or 0) < MIN_RAISE_STREAK:
                return f"a raise with a streak of {streak or 0} years, under {MIN_RAISE_STREAK}"
        case Angle.EX_DIVIDEND:
            if (streak or 0) < MIN_STREAK:
                return f"a streak of {streak or 0} years, under {MIN_STREAK}"
        case Angle.YIELD:
            if stock.yield_band is None or not stock.yield_band.avg_5y:
                return "no 5-year yield band"
    return None


@dataclass(frozen=True)
class Rejected:
    """A company looked up and left out, and why: often a sign of the data's
    quality, which the issue shows the reviewer."""

    symbol: str
    name: str
    angle: Angle
    reason: str


async def _call(
    server: agent.ToolServer,
    tool: Tool[Any],
    arguments: dict[str, Any],
    record: Callable[[Call], None],
) -> tuple[str, bool]:
    """Makes one call, records it as it completes, and returns its result
    and whether it failed. A failure no arguments can fix (the server down)
    is raised once the call is recorded."""
    start = time.monotonic()
    result, failed, error = await agent.call_tool(server, tool, tool.decode_args(arguments))
    record(
        Call(
            tool=tool.name,
            arguments=arguments,
            result=result,
            failed=failed,
            duration=timedelta(seconds=time.monotonic() - start),
        )
    )
    if error is not None:
        raise error
    return result, failed


async def gather(server: agent.ToolServer, record: Callable[[Call], None]) -> None:
    """Makes the day's first calls (first_calls), each recorded. A tool's
    refusal is recorded and leaves its angle without candidates."""
    tools = {t.name: t for t in (DIVIDEND_CHANGES, DIVIDEND_CALENDAR, SCREEN_STOCKS)}
    for name, arguments in first_calls():
        await _call(server, tools[name], arguments, record)


async def look_up(
    server: agent.ToolServer,
    chosen: dict[Angle, list[Candidate]],
    record: Callable[[Call], None],
) -> tuple[list[tuple[Candidate, Stock]], list[Rejected]]:
    """Looks up each angle's candidates with get_stock, in order, until one
    is accepted: the day's companies, and those left out with the reason.
    Each call is recorded as it completes. A failure no arguments can fix
    (the server down) is raised once its call is recorded; a refusal, or a
    reply that doesn't read, leaves that candidate out."""
    accepted: list[tuple[Candidate, Stock]] = []
    rejected: list[Rejected] = []
    for angle in Angle:
        for candidate in chosen.get(angle, []):
            result, failed = await _call(server, GET_STOCK, {"symbol": candidate.symbol}, record)
            if failed:
                rejected.append(Rejected(candidate.symbol, candidate.symbol, angle, result))
                continue
            try:
                stock = Stock.model_validate_json(result)
            except ValidationError:
                rejected.append(
                    Rejected(candidate.symbol, candidate.symbol, angle, "get_stock didn't read")
                )
                continue
            reason = accepts(candidate, stock)
            if reason is None:
                accepted.append((candidate, stock))
                break
            rejected.append(Rejected(candidate.symbol, stock.profile.name, angle, reason))
    return accepted, rejected


# ---- the facts ---------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    """What the writer may say about one company.

    copied holds values exactly as a tool returned them, and is checked
    against the run's calls (provenance.check_data). derived holds what code
    worked out from them: a percentage change, a ratio, a month's name, why
    a yield is high. The writer is shown both, and every figure in a post
    must be one of them."""

    angle: Angle
    symbol: str
    name: str
    copied: dict[str, Any]
    derived: dict[str, Any]

    @property
    def link(self) -> str:
        """The company's page on Quantic, which X shows as a card."""
        return f"{SITE}/stocks/{self.symbol}"

    @property
    def cashtag(self) -> str | None:
        return xpost.cashtag(self.symbol)

    def shown(self) -> dict[str, Any]:
        """What the writer is shown: every value, copied ones first."""
        return {"about": self.angle.value, **self.copied, **self.derived}

    def as_json(self) -> dict[str, Any]:
        """As stored with each version, and read back by from_json."""
        return {
            "angle": self.angle.value,
            "symbol": self.symbol,
            "name": self.name,
            "copied": self.copied,
            "derived": self.derived,
        }

    @classmethod
    def from_json(cls, stored: dict[str, Any]) -> Facts:
        return cls(
            Angle(stored["angle"]),
            stored["symbol"],
            stored["name"],
            stored["copied"],
            stored["derived"],
        )


# Two amounts of one company more than this many times apart aren't in the
# same unit. BAE Systems, 2026-10-28: a last price of 20.17 GBP and a 5-year
# high of 2187.0, in pence; a rate of 0.38 and a dividend history in pence.
UNITS_APART = 20.0


def same_units(a: float, b: float) -> bool:
    """Whether two amounts can be compared, or shown side by side."""
    return a > 0 and b > 0 and 1 / UNITS_APART <= a / b <= UNITS_APART


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        out[key] = value


def facts(candidate: Candidate, stock: Stock, today: date) -> Facts:
    """The facts about a company the writer is shown, built by code from its
    get_stock and the row that made it a candidate. Only what is known goes
    in: a field the tools left empty is left out, not shown as null."""
    profile = stock.profile
    copied: dict[str, Any] = {"company": profile.name, "ticker": profile.symbol}
    derived: dict[str, Any] = {}
    _put(copied, "sector", profile.sector)
    _put(copied, "payment_frequency", profile.payment_frequency)
    dividend = stock.dividend_profile or _DividendProfile()
    _put(copied, "streak_years", dividend.streak_years)
    _put(copied, "safety", dividend.safety.status if dividend.safety else None)
    if dividend.cagr_5y is not None:
        # Per year: named "5y" alone, "grown 8% over five years" was written
        # for 8% a year (BAE Systems, 2026-10-28).
        derived["dividend_growth_per_year_5y_pct"] = round(dividend.cagr_5y * 100, 1)
    paid = profile.payment_months_basis not in (None, "ex_dividend")
    months = sorted(
        set(profile.payment_months if paid else profile.ex_months or profile.payment_months)
    )
    if months:
        # "Hitachi pays in March and September" came from ex-dividend months
        # under a payment name (quantic#521): the fact says which they are.
        all_months, next_month = (
            ("pays_in", "next_payment_month")
            if paid
            else ("goes_ex_dividend_in", "next_ex_dividend_month")
        )
        if len(months) <= 6:  # a monthly payer's twelve months say nothing
            derived[all_months] = [MONTHS[m - 1] for m in months]
        later = [m for m in months if m > today.month]
        derived[next_month] = MONTHS[(later or months)[0] - 1]
    _price(stock, copied, derived)
    _history(stock, today, _rate(candidate, stock), copied, derived)
    match candidate.angle:
        case Angle.CHANGE:
            change = candidate.change
            assert change is not None
            if change.basis == "payment":
                copied |= {
                    "same_payment_a_year_earlier": change.old_rate,
                    "new_payment": change.new_rate,
                }
            else:
                copied |= {"old_annual_rate": change.old_rate, "new_annual_rate": change.new_rate}
            _put(copied, "rate_currency", change.currency)
            copied["seen_on"] = change.detected_on.isoformat()
            derived["change"] = "raise" if change.ratio > 0 else "cut"
            derived["change_pct"] = round(change.ratio * 100, 1)
            derived["change_size_pct"] = abs(derived["change_pct"])
        case Angle.EX_DIVIDEND:
            listed = candidate.listed
            assert listed is not None
            copied["ex_dividend_date"] = listed.ex_dividend_date.isoformat()
            derived["ex_dividend_weekday"] = f"{listed.ex_dividend_date:%A}"
            _put(copied, "pay_date", listed.pay_date.isoformat() if listed.pay_date else None)
            _put(copied, "annual_rate", listed.dividend_rate)
            _put(copied, "rate_currency", listed.currency)
            _put(copied, "current_yield_pct", listed.dividend_yield)
        case Angle.YIELD:
            screened = candidate.screened
            assert screened is not None
            _put(copied, "current_yield_pct", screened.dividend_yield)
    _yield(stock, copied, derived)
    return Facts(candidate.angle, profile.symbol, profile.name, copied, derived)


def _rate(candidate: Candidate, stock: Stock) -> float | None:
    """The annual dividend per share the post quotes, if any: the history's
    amounts are shown next to it only in the same unit."""
    if candidate.change is not None:
        return candidate.change.new_rate
    if candidate.listed is not None and candidate.listed.dividend_rate:
        return candidate.listed.dividend_rate
    last = stock.last_known_price
    screened = candidate.screened
    if last and last.price and screened and screened.dividend_yield:
        return last.price * screened.dividend_yield / 100
    return None


def _history(
    stock: Stock,
    today: date,
    rate: float | None,
    copied: dict[str, Any],
    derived: dict[str, Any],
) -> None:
    """The dividend's history: where Quantic's starts, the last full year,
    and that year against the first and against the 5 before it. The
    amounts are shown only when they are in the unit of the rate the post
    quotes; the ratios between them hold in any unit."""
    by_year = {
        int(year): value
        for year, value in (stock.history.dividend_by_year if stock.history else {}).items()
        if year.isdigit() and int(year) < today.year and value > 0
    }
    if len(by_year) < 2:
        return
    first, last = min(by_year), max(by_year)
    copied |= {"dividend_history_starts": first, "last_full_year": last}
    if rate is None or same_units(rate, by_year[last]):
        copied |= {
            "dividend_per_share_first_year": by_year[first],
            "dividend_per_share_last_full_year": by_year[last],
        }
    derived["years_from_first_to_last_full_year"] = last - first
    derived["last_full_year_times_first_year"] = round(by_year[last] / by_year[first], 2)
    five = [by_year[y] for y in range(last - 4, last + 1) if y in by_year]
    if len(five) == 5:
        derived["last_full_year_times_its_5y_average"] = round(
            by_year[last] / statistics.fmean(five), 2
        )


def _price(stock: Stock, copied: dict[str, Any], derived: dict[str, Any]) -> None:
    """The last price Quantic saw, and how far below the 5-year high it is,
    when both are in the company's own currency."""
    last = stock.last_known_price
    if last is None or last.price is None or last.as_of is None:
        return
    copied["last_known_price"] = last.price
    _put(copied, "price_currency", last.currency)
    derived["last_known_price_as_of"] = last.as_of.date().isoformat()
    high = stock.history.price.high if stock.history and stock.history.price else None
    if high and last.currency == stock.profile.currency and same_units(last.price, high):
        copied["price_high_monthly_5y"] = high
        derived["price_below_5y_high_pct"] = round((1 - last.price / high) * 100, 1)


def _yield(stock: Stock, copied: dict[str, Any], derived: dict[str, Any]) -> None:
    """The current yield against the company's own 5-year band, and, when
    the price explains most of the difference, that as the one cause the
    writer may give.

    The price explains most of it when the yield is further above its
    5-year average than the dividend is above its own: yield = dividend /
    price, so the ratios multiply, and the larger factor is the price's when
    yield ratio > dividend ratio squared. Nike, 2026-10-28: a yield 3.1 times
    its average, a dividend 1.19 times its own, so the price is 2.6 times
    and most of it."""
    band = stock.yield_band
    current: float | None = copied.get("current_yield_pct")
    if band is None or current is None or not band.avg_5y:
        return
    copied["yield_avg_5y_pct"] = band.avg_5y
    times = round(current / band.avg_5y, 2)
    derived["current_yield_times_5y_average"] = times
    if band.high_5y:
        copied["yield_high_5y_pct"] = band.high_5y
        derived["current_yield_times_5y_high"] = round(current / band.high_5y, 2)
    dividend: float | None = derived.get("last_full_year_times_its_5y_average")
    if times >= MIN_YIELD_RATIO and dividend and times > dividend**2:
        derived["why_the_yield_is_high"] = (
            "The yield is above its 5-year average mostly because the share price fell: the "
            f"dividend of the last full year is {dividend} times its 5-year average, while the "
            f"yield is {times} times its 5-year average."
        )


# ---- checking a version ------------------------------------------------------

_SELLING = re.compile(
    r"\b(?:income potential|significant(?:ly)?|impressive|remarkable|juicy|stunning|massive|"
    r"huge|solid|strong|eye-catching|spiking|soaring|plunging|crash(?:ed|ing)?)\b",
    re.IGNORECASE,
)
# The last known price written as current ("$O trades at $56.82", 2026-10-28).
_AS_CURRENT = re.compile(
    r"\b(?:trades? at|trading at|shares are (?:now )?at|currently (?:at|priced))\b", re.IGNORECASE
)
# A figure with a unit glued to it, which the figure check reads as a word: "38p"
# for a rate of 0.38 GBP (BAE Systems, 2026-10-28). Not "5-year", which the
# hyphen separates.
_GLUED = re.compile(r"\b\d+(?:\.\d+)?[a-wyzA-Z]+\b")
# Words that give a cause. The data states one cause only, why_the_yield_is_high;
# without it, "the yield … reflecting 28 straight years of increases" was a cause
# the model made up (Realty Income, 2026-10-28).
_CAUSE = re.compile(
    r"\b(?:because|due to|driven by|drives|driving|reflect(?:s|ing)|backed by|thanks to|"
    r"as a result|explains?)\b",
    re.IGNORECASE,
)
_NOT_PLAIN = re.compile(r"\b(?:5y|avg|DPS|YoY)\b|\b\d+(?:\.\d+)?x\b")
_CAPITALS = re.compile(r"\b[A-Z]{4,}\b")
# Acronyms a post may write in capitals: currency codes and kinds of company.
_ACRONYMS = {"REIT", "REITS", "USD", "EUR", "GBP", "HKD", "SGD", "CHF", "AUD", "CAD", "NOK"}
_A_CASHTAG = re.compile(r"\$[A-Za-z]")
# Typography above U+2100 that isn't an emoji.
_TYPOGRAPHY = set(
    "\N{EN DASH}\N{EM DASH}\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
    "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}\N{HORIZONTAL ELLIPSIS}"
    "\N{MULTIPLICATION SIGN}"
)


def _emojis(text: str) -> list[str]:
    return [c for c in text if ord(c) > 0x2100 and c not in _TYPOGRAPHY and c != "️"]


def manifest(facts: Facts, today: date) -> provenance.Manifest:
    """What a version's figures may trace to: its own company's facts, not
    another's. Traced to every fact, a post naming one company could carry
    another's figures, and in the experiment three linked to the wrong one."""
    found = provenance.Manifest([provenance.Record("facts", json.dumps(facts.shown()))])
    found.add_text("today", f"{today:%A} {today.isoformat()}")
    # The periods the fields are over, which posts name: "its 5-year average".
    found.add_text("the fields' periods", "5-year five-year")
    return found


def names(facts: Facts, text: str) -> bool:
    """Whether text names the company: its ticker, or the first word of its
    name ("Nike" for "Nike, Inc.", "Intertek" for "INTERTEK GROUP PLC")."""
    plain = re.sub(r"['\u2019]", "", text.lower())
    first = re.sub(r"[^\w]", "", facts.name.split()[0]).lower() if facts.name.split() else ""
    ticker = facts.symbol.split(".")[0].lower()
    return ticker in re.findall(r"[\w-]+", plain) or (len(first) >= 3 and first in plain)


def check_version(text: str, facts: Facts, today: date) -> list[str]:
    """What's wrong with one version, as the writer is told it: empty when
    it can be proposed. Figures must be its company's facts; the wording
    rules apply, with "price" allowed and the company's name not read as
    advice; and nothing a post on X is read as spam for."""
    problems = [
        f"a figure not in the data: {f.text!r}"
        for f in provenance.check_prose(text, manifest(facts, today))
    ]
    problems += [
        f"wording ({f.value}): {f.text!r}"
        for f in wording.check(text, names=[facts.name], allow={"price", "prices"})
    ]
    problems += [f"selling language: {m.group()!r}" for m in _SELLING.finditer(text)]
    problems += [f"not plain words: {m.group()!r}" for m in _NOT_PLAIN.finditer(text)]
    problems += [
        f"a figure with a unit glued to it: {m.group()!r}; write it as the data does"
        for m in _GLUED.finditer(text)
    ]
    if "why_the_yield_is_high" not in facts.derived:
        problems += [
            f"a cause: {m.group()!r}; the data gives none, so describe without explaining"
            for m in _CAUSE.finditer(text)
        ]
    problems += [
        f'{m.group()!r}: the price is the last one Quantic saw, say "last known price"'
        for m in _AS_CURRENT.finditer(text)
    ]
    if re.search(r"\bNorthwind\b|\$NWND\b", text):
        problems.append("the prompt's example company, which isn't the data")
    if not names(facts, text):
        problems.append(f"it doesn't name the company, {facts.name}")
    if "!" in text:
        problems.append("an exclamation mark")
    if "#" in text:
        problems.append("a hashtag")
    acronyms = _ACRONYMS | {facts.symbol.split(".")[0]}
    problems += [
        f"a word in capitals: {m.group()}"
        for m in _CAPITALS.finditer(text)
        if m.group() not in acronyms
    ]
    tag = facts.cashtag
    if tag is not None and text.count(tag) != 1:
        problems.append(f"the cashtag {tag} must appear exactly once")
    if tag is None and _A_CASHTAG.search(text):
        problems.append(f"no cashtag: X doesn't make one of {facts.symbol}")
    emojis = _emojis(text)
    if not 1 <= len(emojis) <= 2 or any(e not in EMOJI for e in emojis):
        problems.append(f"one or two emojis from the list, found: {''.join(emojis) or 'none'}")
    elif any(_emojis(line.strip()[1:]) for line in text.splitlines()):
        problems.append(
            "an emoji that doesn't open its paragraph: each emoji goes first in a paragraph, "
            "never at the end of a sentence"
        )
    if len(text) > MAX_TEXT:
        problems.append(f"too long: {len(text)} characters, at most {MAX_TEXT}")
    with_link = xpost.x_length(f"{text}\n\n{facts.link}", (facts.link,))
    if with_link > xpost.LIMIT:
        problems.append(f"too long for X: {with_link} with the link, at most {xpost.LIMIT}")
    return problems


# ---- writing -------------------------------------------------------------------


class _Versions(BaseModel):
    versions: list[str]


VERSIONS_FORMAT = _Versions.model_json_schema()


class NotPostsError(Exception):
    """The model's reply wasn't the versions as JSON. tokens is what it cost."""

    def __init__(self, message: str, tokens: int) -> None:
        super().__init__(message)
        self.tokens = tokens


@dataclass(frozen=True)
class Version:
    """One version of a post, and what's wrong with it: nothing, if it can
    be proposed."""

    text: str
    problems: list[str] = field(default_factory=lambda: list[str]())

    @property
    def ready(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class Written:
    """A company's versions: those that passed, in the order they were
    written, then the last attempt's that didn't."""

    facts: Facts
    versions: list[Version]
    attempts: int
    tokens: int

    @property
    def ready(self) -> list[Version]:
        return [v for v in self.versions if v.ready]


def prompt(versions: int, cashtag: str | None) -> str:
    rule = (
        f"Include the cashtag {cashtag} once, as part of a sentence."
        if cashtag
        else "No cashtag: X doesn't make one of this company's ticker. Name the company."
    )
    return PROMPT.substitute(versions=versions, cashtag_rule=rule, emoji=" ".join(EMOJI))


async def write(
    model: Model,
    facts: Facts,
    today: date,
    *,
    options: llm.Options | None = None,
    versions: int = VERSIONS,
    attempts: int = ATTEMPTS,
) -> Written:
    """Asks the model for versions of a post about one company, and checks
    each. Those that fail are sent back with what's wrong, up to attempts
    times; a version that passed is kept, so a retry that breaks it loses
    nothing."""
    messages = [
        llm.Message(role="system", content=prompt(versions, facts.cashtag)),
        llm.Message(
            role="user",
            content=f"Today is {today:%A} {today.isoformat()}.\n\nThe data:\n"
            + json.dumps(facts.shown(), indent=1),
        ),
    ]
    ready: dict[str, Version] = {}
    tokens = 0
    for attempt in range(1, attempts + 1):
        resp = await model.chat(messages, think=False, format=VERSIONS_FORMAT, options=options)
        tokens += resp.prompt_eval_count + resp.eval_count
        try:
            texts = [
                t.strip() for t in _Versions.model_validate_json(resp.message.content).versions
            ]
        except ValidationError as err:
            raise NotPostsError(f"the reply wasn't the versions as JSON: {err}", tokens) from err
        checked = [Version(t, check_version(t, facts, today)) for t in texts if t]
        for v in checked:
            if v.ready:
                ready.setdefault(v.text, v)
        held = [v for v in checked if not v.ready]
        if len(ready) >= versions or not held or attempt == attempts:
            return Written(facts, [*list(ready.values())[:versions], *held], attempt, tokens)
        messages += [resp.message, llm.Message(role="user", content=_again(checked, versions))]
    raise AssertionError("unreachable: the last attempt returns")


def _again(checked: Sequence[Version], versions: int) -> str:
    lines = [
        f"Version {i}: {'; '.join(v.problems)}" for i, v in enumerate(checked, 1) if v.problems
    ]
    return (
        "Some versions break the rules:\n"
        + "\n".join(lines)
        + f"\nReply with all {versions} versions again, fixing those. Same JSON format."
    )


# ---- the issue -----------------------------------------------------------------

ABOUT = {
    Angle.CHANGE: "a dividend change",
    Angle.EX_DIVIDEND: "an ex-dividend date",
    Angle.YIELD: "its yield against its own history",
}
_TICK = re.compile(r"^- \[([ xX])\] posted (\S+) version (\d+)\s*$", re.MULTILINE)


def title(day: date) -> str:
    return f"X posts for {day:%A} {day.isoformat()}"


def issue_body(
    day: date, run_id: int, written: Sequence[Written], rejected: Sequence[Rejected]
) -> str:
    """The day's issue: each company's versions that passed, ready to copy,
    with a box to tick when one is posted; the facts they were written
    from; and the companies looked up and left out, with why."""
    parts = [
        f"Drafted by quantic-agent from Quantic's data on {day.isoformat()} (run {run_id}: "
        f"`quantic-agent --run {run_id}`). The agent posts nothing. Pick a version, post it "
        "on X, and tick its box; close the issue when you're done. Prices are as of the "
        "date in each company's facts: post the same day.",
    ]
    for w in written:
        if not w.ready:
            continue
        f = w.facts
        parts.append(f"## {f.name} ({f.symbol}): {ABOUT[f.angle]}\n\n{f.link}")
        for i, v in enumerate(w.ready, 1):
            parts.append(
                f"- [ ] posted {f.symbol} version {i}\n\n```text\n{v.text}\n\n{f.link}\n```"
            )
        shown = json.dumps(f.shown(), indent=1, ensure_ascii=False)
        parts.append(
            f"<details><summary>What it was written from</summary>\n\n```json\n{shown}\n```\n"
            "</details>"
        )
    held = [w for w in written if not w.ready]
    if held or rejected:
        lines = [
            f"- {w.facts.name} ({w.facts.symbol}): no version passed the checks after "
            f"{w.attempts} attempts"
            for w in held
        ]
        lines += [f"- {r.name} ({r.symbol}), {ABOUT[r.angle]}: {r.reason}" for r in rejected]
        parts.append("## Looked at and left out\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


def ticks(body: str) -> set[tuple[str, int]]:
    """The versions ticked as posted in an issue's body, as (symbol, version)."""
    return {(m[2], int(m[3])) for m in _TICK.finditer(body) if m[1] in "xX"}
