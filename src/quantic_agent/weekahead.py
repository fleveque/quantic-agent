"""The Dividend Week Ahead (docs/content.md): one post, in seven locales.

Research is agent.Researcher's loop, as for any question: the model decides
which tools to call. What it gathered then becomes a post in three steps, and
in none of them does the model write a figure:

- the data block is built by code from the recorded tool results
  (gather), and checked against them like any data (provenance.check_data);
- the model writes the English prose, which must have no figures at all, and
  is asked again when it has some (write);
- the model translates the prose into each other locale, and each
  translation is checked: no figures, a length near the English (translate).
  A translation that fails is held; the others go ahead.

Every locale's file carries the same data block, serialised once, so no
figure can differ between them: no figure is translated (docs/rendering.md).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from importlib import resources
from string import Template
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quantic_agent import llm, provenance
from quantic_agent.agent import Call, Model
from quantic_agent.tools import DIVIDEND_CALENDAR, GET_STOCK

KIND = "week_ahead"  # the post's kind, and its runs' kind in the store


def _package_file(*parts: str) -> str:
    """A text file shipped inside the package. importlib.resources finds it
    wherever the package is installed: a source checkout, a wheel, a zip."""
    return resources.files("quantic_agent").joinpath(*parts).read_text(encoding="utf-8")


# Prompts are code (design open question 6), reviewed like code, but long
# enough to read better as text files than as string literals.
WRITE_PROMPT = _package_file("prompts", "week_ahead.md")
TRANSLATE_PROMPT = Template(_package_file("prompts", "translate.md"))


@dataclass(frozen=True)
class Locale:
    """One of Quantic's seven locales: the language as the translator is told
    it, register included, and the post's section headings in it."""

    code: str
    language: str
    headings: dict[str, str]


def _locales() -> dict[str, Locale]:
    table: dict[str, dict[str, Any]] = json.loads(_package_file("locales.json"))
    return {code: Locale(code, **entry) for code, entry in table.items()}


LOCALES = _locales()
SOURCE = "en"  # what is written, checked and reviewed; the rest are translated from it
TRANSLATED = tuple(code for code in LOCALES if code != SOURCE)


# ---- the week ----------------------------------------------------------------


@dataclass(frozen=True)
class Week:
    """A week, Monday to Sunday. Its ISO week names the post."""

    start: date  # a Monday

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)

    @property
    def period(self) -> str:
        """The ISO week, "2026-W42". Its year is the ISO year, which is not
        always the calendar year: the week that starts on Monday 2024-12-30
        is 2025-W01."""
        year, week, _ = self.start.isocalendar()
        return f"{year}-W{week:02d}"

    @property
    def slug(self) -> str:
        """The post's name in its URL, /insights/week-ahead-2026-W42."""
        return f"week-ahead-{self.period}"


def week_after(today: date) -> Week:
    """The week after the one today is in. Run on a Sunday, as planned, it is
    the week that starts tomorrow; run on a Monday, the one in seven days."""
    return Week(today + timedelta(days=7 - today.weekday()))


def question(today: date) -> str:
    """What the research loop is asked, for the week after today. It says
    what today is: the calendar counts its days from today, and a model not
    told the date asked for seven of them, which from a Thursday stops short
    of the week's Sunday (docs/benchmarks/2026-10-08-week-ahead/)."""
    week = week_after(today)
    return (
        f"Today is {today:%A} {today.isoformat()}. Gather the data for the Dividend Week "
        f"Ahead, for the week from Monday {week.start.isoformat()} to Sunday "
        f"{week.end.isoformat()}: find every company that goes ex-dividend in that week, "
        "and look up each one."
    )


# ---- the data ----------------------------------------------------------------


class _Data(BaseModel):
    """The post's data. Frozen, and strict about extra fields: nothing gets
    into a published file that the model below doesn't name."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Reason(_Data):
    """Why a dividend has its safety status, as get_stock gives it: a code
    such as "tight_liquidity" and a severity. The template words it."""

    code: str
    severity: str


class ExDividend(_Data):
    """One company going ex-dividend in the week: its calendar entry, and
    the parts of its get_stock profile the post shows. The field names are
    the tools' own, so the file and the audit log use the same words."""

    symbol: str
    name: str
    sector: str | None
    ex_dividend_date: str  # as the calendar wrote it: YYYY-MM-DD
    payment_frequency: str | None
    safety: str | None
    safety_reasons: list[Reason]
    streak_years: int | None
    growth_ttm: float | None  # ratios, as returned: 0.0397, not 3.97%
    cagr_5y: float | None


# What the tools return, read as far as the post needs. Pydantic ignores the
# other fields: get_stock returns far more than the post shows.


class _Listed(BaseModel):
    symbol: str
    name: str
    sector: str | None = None
    ex_dividend_date: date
    payment_frequency: str | None = None


class _Calendar(BaseModel):
    from_: date = Field(alias="from")  # "from" is a Python keyword
    days: int
    stocks: list[_Listed]

    def covers(self, week: Week) -> bool:
        return self.from_ <= week.start and self.from_ + timedelta(days=self.days) >= week.end


class _Safety(BaseModel):
    status: str | None = None
    reasons: list[Reason] = []  # Pydantic copies a default, so a shared [] is safe here


class _DividendProfile(BaseModel):
    safety: _Safety | None = None
    streak_years: int | None = None
    growth_ttm: float | None = None
    cagr_5y: float | None = None


class _Profile(BaseModel):
    symbol: str


class _Stock(BaseModel):
    profile: _Profile
    dividend_profile: _DividendProfile | None = None


class IncompleteError(Exception):
    """Research didn't gather what the post needs. The message says what is
    missing."""


def gather(week: Week, calls: Sequence[Call]) -> list[ExDividend]:
    """The companies going ex-dividend in week, from a run's successful
    calls: the latest calendar that covers the whole week, and each listed
    company's get_stock.

    The model chose the calls, so it may have asked for too short a calendar
    or skipped a company. Either raises IncompleteError: a post that quietly
    left a company out would be wrong about the week.
    """
    calendars: list[_Calendar] = []
    stocks: dict[str, _Stock] = {}
    for c in calls:
        if c.failed:
            continue
        try:
            if c.tool == DIVIDEND_CALENDAR.name:
                calendars.append(_Calendar.model_validate_json(c.result))
            elif c.tool == GET_STOCK.name:
                stock = _Stock.model_validate_json(c.result)
                stocks[stock.profile.symbol] = stock
        except ValidationError as err:
            raise IncompleteError(f"{c.tool} returned something unexpected: {err}") from err

    covering = [cal for cal in calendars if cal.covers(week)]
    if not covering:
        raise IncompleteError(
            f"no dividend_calendar call covers the week {week.start} to {week.end}"
        )
    listed = [s for s in covering[-1].stocks if week.start <= s.ex_dividend_date <= week.end]
    missing = [s.symbol for s in listed if s.symbol not in stocks]
    if missing:
        raise IncompleteError(f"not looked up with get_stock: {', '.join(missing)}")
    return [_row(s, stocks[s.symbol].dividend_profile or _DividendProfile()) for s in listed]


def _row(listed: _Listed, profile: _DividendProfile) -> ExDividend:
    safety = profile.safety or _Safety()
    return ExDividend(
        symbol=listed.symbol,
        name=listed.name,
        sector=listed.sector,
        ex_dividend_date=listed.ex_dividend_date.isoformat(),
        payment_frequency=listed.payment_frequency,
        safety=safety.status,
        safety_reasons=safety.reasons,
        streak_years=profile.streak_years,
        growth_ttm=profile.growth_ttm,
        cagr_5y=profile.cagr_5y,
    )


def data_block(rows: Sequence[ExDividend]) -> dict[str, Any]:
    """The post's data, as plain values: what the file carries, and what
    provenance.check_data checks."""
    return {"ex_dividends": [r.model_dump() for r in rows]}


# ---- the prose ---------------------------------------------------------------


class Prose(BaseModel):
    """The post's prose, one field per section, in the order the post shows
    them. Its JSON Schema is the format the model must answer in."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str  # before the registration gate (fold_after)
    watch: str

    def text(self) -> str:
        """Every section, as one text to check."""
        return "\n\n".join(getattr(self, key) for key in SECTIONS)


SECTIONS = tuple(Prose.model_fields)
PROSE_FORMAT = Prose.model_json_schema()

# How many times the writer is asked for prose with no figures in it.
ATTEMPTS = 3

# The data's field names as the writer is shown them. The tools' own names
# carry figures, and the model repeated them: shown cagr_5y and growth_ttm,
# its prose said "five-year" and "twelve months". Shown these, it didn't once
# in 60 attempts (docs/benchmarks/2026-10-08-week-ahead/). The file keeps the tools' names.
WRITER_NAMES = {
    "streak_years": "consecutive_raises",
    "growth_ttm": "recent_growth",
    "cagr_5y": "long_term_growth",
}


class NotProseError(Exception):
    """The model's reply wasn't the prose's sections, as JSON, each with some
    text. tokens is what the attempt cost."""

    def __init__(self, message: str, tokens: int) -> None:
        super().__init__(message)
        self.tokens = tokens


@dataclass(frozen=True)
class Written:
    """The English prose: the last attempt, the figures still in it (none,
    if it can be published), how many attempts it took and their tokens."""

    prose: Prose
    findings: list[provenance.Finding]
    attempts: int
    tokens: int


async def write(
    model: Model,
    week: Week,
    rows: Sequence[ExDividend],
    *,
    options: llm.Options | None = None,
    attempts: int = ATTEMPTS,
) -> Written:
    """Asks the model for the English prose, shown the week and its data.

    Prose with figures in it is sent back with the figures named, up to
    attempts times in all; the last attempt is returned whatever it holds.
    The data is the file's, under names with no figures in them (WRITER_NAMES).
    """
    shown = json.dumps(data_block(rows), indent=1)
    for name, plain in WRITER_NAMES.items():
        shown = shown.replace(f'"{name}":', f'"{plain}":')
    messages = [
        llm.Message(role="system", content=WRITE_PROMPT),
        llm.Message(
            role="user",
            content=f"The week: Monday {week.start} to Sunday {week.end}\n\nThe data:\n{shown}",
        ),
    ]
    tokens = 0
    for attempt in range(1, attempts + 1):
        resp = await model.chat(messages, think=False, format=PROSE_FORMAT, options=options)
        tokens += resp.prompt_eval_count + resp.eval_count
        prose = _prose(resp, tokens)
        findings = provenance.no_figures(prose.text())
        if not findings or attempt == attempts:
            return Written(prose, findings, attempt, tokens)
        named = ", ".join(repr(f.text) for f in findings)
        messages += [
            resp.message,
            llm.Message(
                role="user",
                content=(
                    f"That prose has figures in it: {named}. The post's tables show every "
                    "figure, so the prose must have none. Write both fields again without "
                    "numbers, dates, counts or durations, in digits or in words."
                ),
            ),
        ]
    raise AssertionError("unreachable: the last attempt returns")


def _prose(resp: llm.ChatResponse, tokens: int) -> Prose:
    try:
        prose = Prose.model_validate_json(resp.message.content)
    except ValidationError as err:
        raise NotProseError(f"the reply wasn't the prose as JSON: {err}", tokens) from err
    empty = [key for key in SECTIONS if not getattr(prose, key).strip()]
    if empty:
        raise NotProseError(f"the reply left out {', '.join(empty)}", tokens)
    return prose


# ---- translation -------------------------------------------------------------

# How long a translated section may be, against the English. Measured: the
# 228 sections of 114 real translations by qwen3.5:9b were 0.95 to 1.37 times
# as long (docs/benchmarks/2026-10-08-week-ahead/).
LENGTH_BAND = (0.75, 1.75)


@dataclass(frozen=True)
class Translation:
    """The prose in one locale, and what's wrong with it, if anything. prose
    is None when the reply wasn't the prose at all; raw is the reply as it
    came."""

    locale: str
    prose: Prose | None
    raw: str
    problems: list[str] = field(default_factory=lambda: list[str]())
    tokens: int = 0


async def translate(
    model: Model, source: Prose, locale: str, *, options: llm.Options | None = None
) -> Translation:
    """The prose translated into locale, and checked (check_translation)."""
    system = TRANSLATE_PROMPT.substitute(language=LOCALES[locale].language)
    messages = [
        llm.Message(role="system", content=system),
        llm.Message(role="user", content=source.model_dump_json()),
    ]
    resp = await model.chat(messages, think=False, format=PROSE_FORMAT, options=options)
    tokens = resp.prompt_eval_count + resp.eval_count
    raw = resp.message.content
    try:
        translated = _prose(resp, tokens)
    except NotProseError as err:
        return Translation(locale, None, raw, [str(err)], tokens)
    return Translation(locale, translated, raw, check_translation(source, translated), tokens)


def check_translation(source: Prose, translated: Prose) -> list[str]:
    """What's wrong with a translation, section by section: figures, which
    the English has none of, and a length outside LENGTH_BAND, the sign of
    something added or left out. Empty when it can be published.

    Its sections are the English's by construction: the reply is parsed into
    Prose, which has those fields and refuses others. The figure check knows
    numbers in digits in every language, but numbers in words only in
    English: a "dues" in Catalan passes.
    """
    problems: list[str] = []
    low, high = LENGTH_BAND
    for key in SECTIONS:
        text = getattr(translated, key)
        problems += [f"{key}: figure {f.text!r}" for f in provenance.no_figures(text)]
        ratio = len(text) / len(getattr(source, key))
        if not low <= ratio <= high:
            problems.append(
                f"{key}: {ratio:.2f} times as long as the English, outside {low}-{high}"
            )
    return problems


# ---- the file ----------------------------------------------------------------


class _Quoted(str):
    """A string to write double-quoted in YAML, whatever it looks like."""


class _Dumper(yaml.SafeDumper):
    """YAML's own rules leave strings unquoted when they don't look like
    something else, and which strings look like something else depends on
    the parser: PyYAML writes 1e3 bare and reads it back as a string, a YAML
    1.2 parser reads it as a number. Every string value is quoted, so the
    Phoenix side reads exactly the text that was checked here."""


def _represent_quoted(dumper: yaml.SafeDumper, value: _Quoted) -> yaml.ScalarNode:
    # The stubs leave represent_scalar's value untyped.
    return dumper.represent_scalar(  # pyright: ignore[reportUnknownMemberType]
        "tag:yaml.org,2002:str", value, style='"'
    )


_Dumper.add_representer(_Quoted, _represent_quoted)


def _quoted(value: Any) -> Any:
    """value with every string in it marked to be quoted; keys stay bare."""
    match value:
        case str():
            return _Quoted(value)
        case list():
            return [_quoted(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
        case dict():
            return {k: _quoted(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
        case _:
            return value


def _yaml(value: dict[str, Any]) -> str:
    return yaml.dump(_quoted(value), Dumper=_Dumper, sort_keys=False, allow_unicode=True)


def data_yaml(rows: Sequence[ExDividend]) -> str:
    """The data block as YAML: serialised once, and written into every
    locale's file as it is, so the seven are byte-identical where it counts."""
    return _yaml({"data": data_block(rows)})


def render(week: Week, run_id: int, locale: str, data: str, prose: Prose) -> str:
    """One locale's file: YAML frontmatter (what the post is, and its data)
    and a markdown body with one section per prose field, under the locale's
    headings. data is data_yaml's output."""
    head = _yaml(
        {
            "kind": KIND,
            "period": week.period,
            "locale": locale,
            "week_start": week.start.isoformat(),
            "week_end": week.end.isoformat(),
            "run_id": run_id,  # where its provenance is: quantic-agent --run N
            "fold_after": SECTIONS[0],  # the registration gate opens after the summary
            "sections": list(SECTIONS),
        }
    )
    headings = LOCALES[locale].headings
    body = "\n".join(f"## {headings[key]}\n\n{getattr(prose, key)}\n" for key in SECTIONS)
    return f"---\n{head}{data}---\n\n{body}"


def read_back(text: str, locale: str) -> tuple[dict[str, Any], dict[str, str]]:
    """A file as a reader of it sees it: its frontmatter, and its sections'
    text by key. Raises ValueError when it isn't a post's shape."""
    if not text.startswith("---\n"):
        raise ValueError("no frontmatter")
    head, end, body = text.removeprefix("---\n").partition("\n---\n")
    if not end:
        raise ValueError("the frontmatter doesn't end")
    front: dict[str, Any] = yaml.safe_load(head)
    keys = {heading: key for key, heading in LOCALES[locale].headings.items()}
    sections: dict[str, str] = {}
    key = ""
    for line in body.splitlines():
        if line.startswith("## "):
            if line[3:] not in keys:
                raise ValueError(f"an unexpected heading: {line!r}")
            key = keys[line[3:]]
            sections[key] = ""
        elif key:
            sections[key] += line + "\n"
        elif line.strip():
            raise ValueError("text before the first heading")
    return front, {k: v.strip() for k, v in sections.items()}


def check_file(text: str, locale: str, rows: Sequence[ExDividend], prose: Prose) -> list[str]:
    """Whether the file, read back, says what was checked: the data block
    equal to the data, and each section equal to the prose. Prose that
    writes its own "## " heading, or YAML that a value broke, fails here,
    before anything is published."""
    try:
        front, sections = read_back(text, locale)
    except (ValueError, yaml.YAMLError) as err:
        return [f"the file doesn't read back: {err}"]
    problems: list[str] = []
    if front.get("data") != data_block(rows):
        problems.append("the file's data block doesn't read back as the data")
    if front.get("locale") != locale:
        problems.append(f"the file's locale reads back as {front.get('locale')!r}")
    if sections != {key: getattr(prose, key).strip() for key in SECTIONS}:
        problems.append("the file's sections don't read back as the prose")
    return problems
