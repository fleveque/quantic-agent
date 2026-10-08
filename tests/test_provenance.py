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
        pytest.param(CAL, "Oct 21 is busy", [], id="the day isn't checked twice"),
        pytest.param(CAL, "on October 16 and 17", [], id="a second day sharing the month"),
        pytest.param(
            CAL,
            "on October 17 and 18",
            ["October 17 and 18"],
            id="a second day that wasn't returned",
        ),
        pytest.param(CAL, "on 16 & 17 October", [], id="a day pair before the month"),
        # A real answer's "Oct 8-10" read as a date and the number -10.
        pytest.param(CAL, "between Oct 8-10 and Oct 16\u201317", [], id="ranges of days"),
        pytest.param(CAL, "from Oct 17-18", ["Oct 17-18"], id="a range ending on another day"),
        pytest.param(CAL, "on 2026-10-08 October brings", [], id="an ISO date isn't a range"),
        # Numbers in words are figures too. A list's length counts as
        # returned: the calendar has ten stocks.
        pytest.param(CAL, "ten stocks go ex-dividend", [], id="a count that matches the list"),
        pytest.param(CAL, "eleven stocks go ex-dividend", ["eleven"], id="a count that doesn't"),
        pytest.param(CAL, "about four months", ["four"], id="a derived duration in words"),
        pytest.param(QUOTE, "twenty-one days", ["twenty-one"], id="a compound number"),
        pytest.param(CAL, "a six-month window", ["six"], id="a word number as an adjective"),
        pytest.param(CAL, "one of them pays monthly", [], id="one is a pronoun, not a figure"),
        # A weekday written with a date must be that date's. October 9 is a
        # Friday: the claim milestone 7's audit log passed.
        pytest.param(CAL, "Apple on Friday, October 9", [], id="the right weekday"),
        pytest.param(
            CAL, "Apple on Tuesday, October 9", ["Tuesday, October 9"], id="a wrong weekday"
        ),
        pytest.param(CAL, "Apple (Fri 9 Oct)", [], id="an abbreviated weekday"),
        pytest.param(
            CAL, "on 2026-10-09 (Thursday)", ["2026-10-09 (Thursday)"], id="a weekday after"
        ),
        pytest.param(
            CAL,
            "on Saturday, October 16 and 17",
            ["Saturday, October 16 and 17"],
            id="a weekday goes with the first day of a pair",
        ),
        pytest.param(CAL, "on Friday", [], id="a weekday alone isn't checked"),
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
            "Several consumer-staples names go ex-dividend in the same week "
            "for the first time this quarter.",
            [],
        ),
        # ...a count in words, which nothing in a post's prose can verify...
        ("Three consumer-staples names go ex-dividend in the same week.", ["Three"]),
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


def test_a_wrong_weekday_says_what_the_date_is() -> None:
    [finding] = check_prose("Apple goes ex-dividend on Tuesday, October 9.", CAL)
    assert str(finding) == "'Tuesday, October 9' (date --10-09, but 2026-10-09 is a Friday)"


def test_text_as_a_source() -> None:
    # Figures from text added as a source, such as the question, are
    # accounted for; ones it doesn't contain are still reported.
    m = calendar_120()
    m.add_text("question", "Which stocks go ex-dividend in the next six months?")
    m.add_text("today", "2026-10-07")

    found = check_prose("Over the next six months (from 2026-10-07): about four months of data.", m)

    assert [f.text for f in found] == ["four"]
    assert [str(s) for s in m.number(6)] == ["question: 'six'"]


def test_a_list_length_is_a_source() -> None:
    assert [str(s) for s in CAL.number(10)] == ["dividend_calendar#0 len($.stocks)"]


def get_stock_msft() -> Manifest:
    """The real get_stock result for MSFT, captured from quantic.finance."""
    result = (FIXTURES / "provenance" / "get-stock-msft.json").read_text()
    return Manifest([Record("get_stock", result)])


@pytest.mark.parametrize(
    ("text", "reported"),
    [
        # dividend_by_year is keyed by year: "2014": 1.12. A real answer said
        # this, and the years were reported until keys were indexed.
        ("The dividend went from $1.12 in 2014 to $3.32 in 2025.", []),
        # The price history runs "from": "2020-10": a year-month, not a date.
        ("Prices since 2020 ranged from 202.47 to 533.5.", []),
        ("Raised for 15 years in a row.", []),
        # cagr_5y is 0.10230450734403207: as a percentage, it's converted.
        ("Five-year growth of 10.23%.", ["Five", "10.23%"]),
        ("A dividend of 3.6 in 2013.", ["3.6", "2013"]),
    ],
)
def test_get_stock(text: str, reported: list[str]) -> None:
    assert [f.text for f in check_prose(text, get_stock_msft())] == reported
