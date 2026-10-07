import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from quantic_agent.provenance import (
    Manifest,
    ProvenanceError,
    Record,
    check_data,
    check_prose,
    no_figures,
)

FIXTURES = Path(__file__).parent / "fixtures"


def calendar_120() -> Manifest:
    """The real dividend_calendar result for 120 days from 2026-10-06, captured
    from quantic.finance: the data behind lesson 05's answer that claimed
    "180 days"."""
    result = (FIXTURES / "provenance" / "calendar-120.json").read_text()
    return Manifest([Record("dividend_calendar", result)])


def manifest(*results: str) -> Manifest:
    """One from literal JSON results, for values the calendar doesn't have."""
    return Manifest(Record("test", r) for r in results)


CAL = calendar_120()
QUOTE = manifest(
    '{"symbol":"O","amount":0.2695,"yield_pct":5.42,"market_cap":1234.5,"change_pct":-3.5,"rank":1}'
)


@pytest.mark.parametrize(
    ("m", "text", "reported"),
    [
        # The case that motivated this milestone: 120 days of data, 180 claimed.
        pytest.param(
            CAL,
            "here are the companies that have ex-dividend dates within the next 180 days",
            ["180"],
            id="the claim from lesson 05",
        ),
        pytest.param(CAL, "the stocks going ex-dividend in the next 120 days", [], id="the window"),
        pytest.param(CAL, "in the next 4 months", ["4"], id="a derived figure"),
        pytest.param(CAL, "MSFT goes ex-dividend on 2026-10-08.", [], id="ISO date"),
        pytest.param(
            CAL, "MSFT goes ex-dividend on 2026-10-07.", ["2026-10-07"], id="ISO not returned"
        ),
        pytest.param(CAL, "Microsoft (Oct 8) and Apple (Oct 9)", [], id="month and day"),
        pytest.param(CAL, "Apple on Oct 11", ["Oct 11"], id="month and day not returned"),
        pytest.param(CAL, "on October 8, 2026", [], id="full date"),
        pytest.param(CAL, "on 8 October 2026", [], id="day before month"),
        pytest.param(CAL, "on October 16th", [], id="ordinal day"),
        pytest.param(CAL, "Oct 21 brings two", [], id="the day isn't checked twice"),
        pytest.param(CAL, "the 2026 calendar", [], id="year of a returned date"),
        pytest.param(CAL, "by 2027", ["2027"], id="year with no returned date"),
        pytest.param(QUOTE, "pays 0.2695 per share", [], id="exact amount"),
        pytest.param(QUOTE, "pays about 0.27 per share", ["0.27"], id="rounded amount"),
        pytest.param(QUOTE, "pays $0.2695", [], id="currency symbol"),
        pytest.param(QUOTE, "yields 5.42%", [], id="percent"),
        pytest.param(QUOTE, "a market cap of 1,234.5", [], id="thousands separator"),
        pytest.param(QUOTE, "fell -3.5%", [], id="negative percent"),
        pytest.param(
            CAL, "Q3 results, week W38, a 3M position, qwen3.5 wrote it", [], id="digits in words"
        ),
        pytest.param(CAL, "unlike COVID-19", [], id="a hyphenated code"),
        pytest.param(CAL, "1. Realty Income\n2. Microsoft\n10. Diageo", [], id="list positions"),
        pytest.param(CAL, "180 days ahead", ["180"], id="a line start that isn't a list"),
        pytest.param(
            CAL,
            "In 3 weeks, on Oct 30, 12 companies",
            ["3", "Oct 30", "12"],
            id="several, in order",
        ),
        pytest.param(CAL, "Utilities and healthcare names lead the week.", [], id="no figures"),
    ],
)
def test_check_prose(m: Manifest, text: str, reported: list[str]) -> None:
    assert [f.text for f in check_prose(text, m)] == reported


def test_a_boolean_accounts_for_no_number() -> None:
    # json.loads gives True for true, and True == 1 in Python, with the same
    # hash: indexed as a number, "done": true would account for a "1".
    m = manifest('{"done": true, "partial": false, "count": 2}')
    assert [f.text for f in check_prose("1 company, 0 cuts, 2 raises", m)] == ["1", "0"]


def test_an_integer_and_its_float_are_the_same_figure() -> None:
    assert check_prose("in the next 10.0 days", manifest('{"days": 10}')) == []


def test_a_real_answer_passes() -> None:
    # The answer qwen3.5:9b wrote in milestone 5, against the data it was given.
    answer = json.loads((FIXTURES / "ollama" / "chat-tool-answer.json").read_text())
    sse = (FIXTURES / "mcp" / "call-dividend-calendar.sse").read_text()
    data_line = next(line for line in sse.splitlines() if line.startswith("data: "))
    result = json.loads(data_line.removeprefix("data: "))["result"]["content"][0]["text"]

    m = Manifest([Record("dividend_calendar", result)])
    assert check_prose(answer["message"]["content"], m) == []


@pytest.mark.parametrize(
    ("text", "reported"),
    [
        # The example docs/rendering.md gives of prose a post may contain...
        (
            "Three consumer-staples names go ex-dividend in the same week "
            "for the first time this quarter.",
            [],
        ),
        # ...and of prose it may not.
        ("Yields rose about 40 basis points.", ["40"]),
        ("Microsoft goes ex-dividend on Oct 8.", ["Oct 8"]),
        ("The 2026 season.", ["2026"]),
    ],
)
def test_no_figures(text: str, reported: list[str]) -> None:
    assert [f.text for f in no_figures(text)] == reported


DATA = manifest(
    '{"stocks":[{"symbol":"MSFT","ex_dividend_date":"2026-10-08"},'
    '{"symbol":"O","ex_dividend_date":"2026-10-06"}]}',
    '{"symbol":"MSFT","dividend":{"amount":0.83,"currency":"USD","yield_pct":0.71}}',
)


class ExDividend(BaseModel):
    symbol: str
    ex_date: str
    amount: float
    currency: str
    yield_pct: float


class Post(BaseModel):
    ex_dividends: list[ExDividend]


def row(symbol: str = "MSFT", ex_date: str = "2026-10-08", yield_pct: float = 0.71) -> ExDividend:
    return ExDividend(
        symbol=symbol, ex_date=ex_date, amount=0.83, currency="USD", yield_pct=yield_pct
    )


@pytest.mark.parametrize(
    ("data", "reported"),
    [
        pytest.param(Post(ex_dividends=[row()]), [], id="everything traced"),
        pytest.param(
            Post(ex_dividends=[row(yield_pct=0.7)]),
            ["ex_dividends[0].yield_pct = 0.7"],
            id="a rounded yield",
        ),
        pytest.param(
            Post(ex_dividends=[row(symbol="MSFTX")]),
            ["ex_dividends[0].symbol = MSFTX"],
            id="an invented ticker",
        ),
        pytest.param(
            Post(ex_dividends=[row(), row(symbol="O", ex_date="2026-10-07")]),
            ["ex_dividends[1].ex_date = 2026-10-07"],
            id="a date no tool returned, second row",
        ),
        # A dict works as a model does; findings come in the data's own order.
        pytest.param(
            {"zeta": 9.99, "alpha": "nope", "symbol": "O"},
            ["zeta = 9.99", "alpha = nope"],
            id="a dict, two findings",
        ),
    ],
)
def test_check_data(data: object, reported: list[str]) -> None:
    assert [str(f) for f in check_data(data, DATA)] == reported


def test_check_data_takes_a_dataclass() -> None:
    @dataclass
    class Raise:
        symbol: str
        new_amount: float

    assert [str(f) for f in check_data(Raise("MSFT", 0.91), DATA)] == ["new_amount = 0.91"]


def test_the_manifest_records_where_values_came_from() -> None:
    sources = CAL.date("2026-10-08")
    assert len(sources) == 2  # JNJ and MSFT
    assert str(sources[0]).startswith("dividend_calendar#0 $.stocks[")
    assert str(sources[0]).endswith("].ex_dividend_date")
    assert len(CAL.number(120)) == 1  # the window, once


def test_results_must_be_json() -> None:
    with pytest.raises(ProvenanceError, match="not JSON"):
        Manifest([Record("calc", "3.3 percent")])
