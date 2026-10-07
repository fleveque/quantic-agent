"""Every figure the agent writes has to come from a tool (design N1, §3.3).

A run's successful tool calls are indexed into a Manifest: every number, date
and string their results contain, with where each one came from. Output is
then checked against it, in one of three ways:

- check_data walks structured data, the typed fields of a post, and requires
  every number and string in it to be in the manifest. This is the exact check
  the post format exists to make possible (docs/rendering.md).
- check_prose extracts the figures from free text, such as a research answer,
  and reports the ones no tool returned.
- no_figures reports every figure in a post's prose, which must have none.

Matching is exact. A figure the model rounded, converted or calculated is not
the figure a tool returned, so it is reported: derived figures must come from
the calculator tools, where they enter the manifest like any other result.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import TypeAdapter


class ProvenanceError(Exception):
    """A tool result the manifest can't index, so its figures could not be
    accounted for."""


@dataclass(frozen=True)
class Record:
    """One successful tool call: which tool, and the text it returned. Calls
    that failed are not records: an error message is not data."""

    tool: str
    result: str


@dataclass(frozen=True)
class Source:
    """Where a value was found: the call's position in the run, the tool, and
    the value's path inside that call's result."""

    call: int
    tool: str
    path: str

    def __str__(self) -> str:
        return f"{self.tool}#{self.call} {self.path}"


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# What json.loads can return, defined in terms of itself.
type JSON = bool | int | float | str | list[JSON] | dict[str, JSON] | None


class Manifest:
    """Every number, date and string a run's tools returned."""

    def __init__(self, records: Iterable[Record]) -> None:
        # Keys are compared by value, so 10 and 10.0 are one key: a figure
        # written "10.0" is found as the integer 10 a tool returned.
        self._numbers: dict[int | float, list[Source]] = {}
        self._strings: dict[str, list[Source]] = {}
        self._dates: dict[str, list[Source]] = {}  # YYYY-MM-DD
        for i, record in enumerate(records):
            try:
                value: JSON = json.loads(record.result)
            except json.JSONDecodeError as err:
                raise ProvenanceError(
                    f"result of {record.tool} (call {i}) is not JSON: {err}"
                ) from err
            self._index(value, Source(call=i, tool=record.tool, path="$"))

    def _index(self, value: JSON, at: Source) -> None:
        match value:
            # bool first: True is an int in Python (True == 1, and they hash
            # alike), so "done": true would otherwise account for a "1".
            case bool() | None:
                pass  # booleans and nulls carry no figures
            case int() | float():
                self._numbers.setdefault(value, []).append(at)
            case str():
                self._strings.setdefault(value, []).append(at)
                if _ISO_DATE.fullmatch(value):
                    self._dates.setdefault(value, []).append(at)
            case list():
                for i, item in enumerate(value):
                    self._index(item, _child(at, f"[{i}]"))
            case dict():
                for key, item in value.items():
                    self._index(item, _child(at, f".{key}"))

    def number(self, n: float) -> list[Source]:
        """Where n appears, if anywhere."""
        return self._numbers.get(n, [])

    def date(self, iso: str) -> list[Source]:
        """Where a YYYY-MM-DD date appears, if anywhere."""
        return self._dates.get(iso, [])

    def string(self, s: str) -> list[Source]:
        """Where a string value appears, if anywhere. Dates are strings too."""
        return self._strings.get(s, [])

    def has_year(self, year: int) -> bool:
        """Whether any date falls in year. A bare year in prose ("in 2026") is
        accounted for by a returned date in that year: the year is part of a
        figure a tool returned."""
        return any(d.startswith(f"{year:04d}-") for d in self._dates)

    def has_month_day(self, month: int, day: int) -> bool:
        """Whether any date falls on this month and day, in any year, for prose
        that names a date without its year ("Oct 8")."""
        return any(d.endswith(f"-{month:02d}-{day:02d}") for d in self._dates)


def _child(at: Source, step: str) -> Source:
    return Source(call=at.call, tool=at.tool, path=at.path + step)


# ---- structured data -------------------------------------------------------


@dataclass(frozen=True)
class DataFinding:
    """A value in structured data that no tool returned."""

    path: str  # where in the data: "ex_dividends[0].amount"
    value: object

    def __str__(self) -> str:
        return f"{self.path} = {self.value}"


_AS_JSON: TypeAdapter[Any] = TypeAdapter(Any)


def check_data(data: object, manifest: Manifest) -> list[DataFinding]:
    """Every value in data that the manifest doesn't contain.

    data is a post's typed data block: a Pydantic model, a dataclass, a dict,
    anything Pydantic can turn into JSON. Every number and every string in it
    must be one a tool returned, exactly. That is the point of keeping figures
    out of prose and in typed fields: "ex_dividends[0].amount is 0.83" is
    checked by lookup, not by parsing text (docs/rendering.md).

    Strings are held to the same rule as numbers, so an invented ticker or a
    date no tool returned is caught too. Findings come in the data's own
    order: Python's dicts keep the order keys were inserted in.
    """
    findings: list[DataFinding] = []
    _check(_AS_JSON.dump_python(data, mode="json"), "", manifest, findings)
    return findings


def _check(value: JSON, path: str, manifest: Manifest, out: list[DataFinding]) -> None:
    match value:
        case bool() | None:
            pass
        case int() | float():
            if not manifest.number(value):
                out.append(DataFinding(path, value))
        case str():
            if not manifest.string(value):
                out.append(DataFinding(path, value))
        case list():
            for i, item in enumerate(value):
                _check(item, f"{path}[{i}]", manifest, out)
        case dict():
            for key, item in value.items():
                _check(item, f"{path}.{key}" if path else key, manifest, out)


# ---- prose -----------------------------------------------------------------


class Kind(StrEnum):
    NUMBER = "number"
    DATE = "date"
    YEAR = "year"


@dataclass(frozen=True)
class Finding:
    """A figure in prose that no tool returned."""

    text: str  # as written: "$0.83", "October 8, 2026", "180"
    offset: int  # character offset in the checked text
    kind: Kind
    value: str  # normalised: "0.83", "2026-10-08", "--10-08" for a date with no year

    def __str__(self) -> str:
        return f"{self.text!r} ({self.kind} {self.value})"


@dataclass(frozen=True)
class _Figure:
    """One figure found in prose, before it is checked."""

    text: str
    offset: int
    kind: Kind
    number: int | float = 0
    year: int = 0  # dates: 0 when the text names no year
    month: int = 0
    day: int = 0

    def value(self) -> str:
        match self.kind:
            case Kind.DATE if self.year == 0:
                return f"--{self.month:02d}-{self.day:02d}"
            case Kind.DATE:
                return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
            case Kind.YEAR:
                return str(self.year)
            case Kind.NUMBER:
                return str(self.number)

    def finding(self) -> Finding:
        return Finding(self.text, self.offset, self.kind, self.value())

    def accounted_for(self, manifest: Manifest) -> bool:
        match self.kind:
            case Kind.DATE if self.year == 0:
                return manifest.has_month_day(self.month, self.day)
            case Kind.DATE:
                return bool(manifest.date(self.value()))
            case Kind.YEAR:
                return bool(manifest.number(self.year)) or manifest.has_year(self.year)
            case Kind.NUMBER:
                return bool(manifest.number(self.number))


def check_prose(text: str, manifest: Manifest) -> list[Finding]:
    """The figures in text that the manifest doesn't account for. An empty
    list means every figure traces to a tool result.

    It recognises numbers (with thousands separators, a currency symbol or a
    percent sign), dates (2026-10-08, "Oct 8", "October 8, 2026", "8 October")
    and bare years. Figures written as words ("five companies") are not seen;
    the post format makes that moot, since its prose may hold no figures at
    all (see no_figures).
    """
    return [f.finding() for f in _figures(text) if not f.accounted_for(manifest)]


def no_figures(text: str) -> list[Finding]:
    """Every figure in text. A post's prose must have none: its figures belong
    in the typed data, where check_data verifies them exactly."""
    return [f.finding() for f in _figures(text)]


_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec"
)
_ISO_IN_PROSE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})\b")
_MONTH_DAY = re.compile(
    rf"\b(?P<month>{_MONTHS})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>\d{{4}})\b)?",
    re.IGNORECASE,
)
_DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTHS})\b\.?(?:,?\s+(?P<year>\d{{4}})\b)?",
    re.IGNORECASE,
)
# A number: an optional sign and currency symbol, digits with or without
# thousands separators, an optional decimal part and percent sign.
_NUMBER = re.compile(r"-?[$€£]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
_NOT_DIGITS = str.maketrans("", "", ",$€£%")


def _figures(text: str) -> list[_Figure]:
    """Every figure in text, in order. Dates are found first and blanked out,
    so the "8" in "Oct 8" isn't also read as a number."""
    found: list[_Figure] = []
    masked = text

    for pattern in (_ISO_IN_PROSE, _MONTH_DAY, _DAY_MONTH):
        for m in pattern.finditer(masked):
            month = m["month"]
            found.append(
                _Figure(
                    text=text[m.start() : m.end()],
                    offset=m.start(),
                    kind=Kind.DATE,
                    year=int(m["year"]) if m["year"] else 0,
                    month=int(month) if month.isdigit() else _month_number(month),
                    day=int(m["day"]),
                )
            )
            # Same length, so every later offset still points into text.
            masked = masked[: m.start()] + " " * (m.end() - m.start()) + masked[m.end() :]

    for m in _NUMBER.finditer(masked):
        if _part_of_word(masked, m.start(), m.end()) or _list_marker(masked, m.start(), m.end()):
            continue
        raw = m.group()
        clean = raw.translate(_NOT_DIGITS)
        number: int | float = float(clean) if "." in clean else int(clean)
        # A bare four-digit integer from 1900 to 2100 reads as a year.
        if clean == raw and isinstance(number, int) and 1900 <= number <= 2100 and len(raw) == 4:
            found.append(_Figure(text=raw, offset=m.start(), kind=Kind.YEAR, year=number))
        else:
            found.append(_Figure(text=raw, offset=m.start(), kind=Kind.NUMBER, number=number))

    return sorted(found, key=lambda f: f.offset)


def _part_of_word(s: str, start: int, end: int) -> bool:
    """Whether the digits at s[start:end] belong to a word such as "Q3", "W38",
    "qwen3.5", "3M" or "COVID-19", rather than standing alone."""
    # A space stands for the text's edges: "" in "._" is True, since the
    # empty string is a substring of every string.
    before = s[start - 1] if start > 0 else " "
    after = s[end] if end < len(s) else " "
    return before.isalnum() or before in "._" or after.isalnum() or after == "_"


def _list_marker(s: str, start: int, end: int) -> bool:
    """Whether the number is a list position at the start of a line ("1. ",
    "2) "): a position, not a claim."""
    line_start = s.rfind("\n", 0, start) + 1
    if s[line_start:start].strip():
        return False
    return s[end : end + 2] in (". ", ") ")


def _month_number(name: str) -> int:
    prefixes = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    return next(i for i, p in enumerate(prefixes, 1) if name.lower().startswith(p))
