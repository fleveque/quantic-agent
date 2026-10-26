from datetime import date

import pytest

from quantic_agent import xpost
from quantic_agent.weekahead import DividendChange, Earning, ExDividend, Week, WeekData

W44 = Week(date(2026, 10, 26))
URL = "quantic.finance/insights/2026/week-ahead-W44"


def ex(symbol: str, streak: int | None = None) -> ExDividend:
    return ExDividend(
        symbol=symbol,
        name=symbol,
        sector=None,
        ex_dividend_date="2026-10-30",
        payment_frequency="quarterly",
        safety="safe",
        safety_reasons=[],
        streak_years=streak,
        growth_ttm=None,
        cagr_5y=None,
        dividend_rate=None,
        currency="USD",
        dividend_yield=None,
        pay_date=None,
    )


def change(symbol: str, old: float, new: float, name: str | None = None) -> DividendChange:
    return DividendChange(
        symbol=symbol,
        name=name or symbol,
        sector=None,
        old_rate=old,
        new_rate=new,
        currency="USD",
        detected_on="2026-10-23",
    )


def earning(symbol: str) -> Earning:
    return Earning(
        symbol=symbol,
        name=symbol,
        sector=None,
        earnings_date="2026-10-28",
        earnings_date_end=None,
        estimated=False,
    )


def test_the_week_in_one_post() -> None:
    # W44 as published: the longest streaks get the cashtags, the biggest
    # raises and cut are named, a non-US listing by its name.
    data = WeekData(
        ex_dividends=[ex("ITX.MC", 30), ex("AOS", 28), ex("RY", 10), ex("O", 28), ex("CLX", 23)],
        earnings=[earning(f"E{i}") for i in range(202)],
        dividend_changes=[
            change("WST", 0.88, 1.04),
            change("WDC", 0.6, 0.7),
            change("0327.HK", 0.33, 0.08, name="PAX GLOBAL"),
            change("KMI", 1.18, 1.19),
        ],
    )

    post = xpost.draft(W44, data)

    assert post == (
        "Dividend Week Ahead, Oct 26 \N{EN DASH} Nov 1:\n\n"
        "📅 5 companies go ex-dividend, incl. $AOS and $O\n"
        "📈 Recent raises: $WST +18%, $WDC +17%\n"
        "📉 Pax Global cut its dividend 76%\n"
        "📊 202 earnings reports\n\n"
        "Day by day, with safety reads 👇\n"
        f"{URL}\n\n"
        "#DividendInvesting #Dividends"
    )
    assert xpost.x_length(post, (URL,)) <= xpost.LIMIT


def test_one_company_and_no_changes() -> None:
    post = xpost.draft(
        W44, WeekData(ex_dividends=[ex("IBE.MC", 3)], earnings=[], dividend_changes=[])
    )

    assert "📅 1 company goes ex-dividend\n" in post
    assert "📈" not in post
    assert "📉" not in post
    assert "📊" not in post


def test_a_change_under_one_percent_is_not_named() -> None:
    # Mostly a listing's rate moving with the exchange rate (quantic#509).
    data = WeekData(
        ex_dividends=[ex("KO", 60)],
        earnings=[],
        dividend_changes=[change("KMI", 1.18, 1.19), change("GUI.DE", 0.54, 0.536)],
    )

    post = xpost.draft(W44, data)

    assert "KMI" not in post
    assert "📈" not in post
    assert "📉" not in post


def test_x_counts_a_link_as_23_and_an_emoji_as_two() -> None:
    assert xpost.x_length("ab", ()) == 2
    assert xpost.x_length("📅", ()) == 2
    assert xpost.x_length("Oct 26 \N{EN DASH} Nov 1", ()) == 14
    assert xpost.x_length(f"see {URL}", (URL,)) == 4 + 23


@pytest.mark.parametrize(
    ("names", "dropped"),
    [
        (60, ["📊"]),
        (90, ["📊", "📉"]),
        (130, ["📊", "📉", "📈"]),
    ],
)
def test_lines_are_dropped_in_order_until_it_fits(names: int, dropped: list[str]) -> None:
    long = "Very Long Company Name Incorporated Holdings"[: names // 2]
    data = WeekData(
        ex_dividends=[ex("KO", 60)],
        earnings=[earning("E")],
        dividend_changes=[
            change("AA.L", 1.0, 1.2, name=long),
            change("BB.L", 1.0, 1.1, name=long),
            change("CC.L", 1.0, 0.5, name=long * 3),
        ],
    )

    post = xpost.draft(W44, data)

    assert xpost.x_length(post, (URL,)) <= xpost.LIMIT
    for mark in dropped:
        assert mark not in post
