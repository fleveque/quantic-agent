import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest
import yaml
from conftest import tool_result
from test_agent import FakeServer, ScriptedModel, answers

from quantic_agent import provenance, quantic, weekahead
from quantic_agent.agent import Call
from quantic_agent.weekahead import Prose, Week, WeekData

# The week after Thursday 2026-10-08, when the first fixtures were captured:
# Procter & Gamble and Coca-Cola go ex-dividend in it.
WEEK = Week(date(2026, 10, 12))

# The week after Wednesday 2026-10-14, when the earnings and dividend changes
# were captured, with a calendar and lookups to go with them: Apple and
# Iberdrola go ex-dividend in it, and Iberdrola reports earnings.
NEXT = Week(date(2026, 10, 19))


def calls(*names: str) -> list[Call]:
    """Successful calls answered by captured tools/call replies."""
    tools = {
        "calendar": "dividend_calendar",
        "get-stock": "get_stock",
        "earnings": "earnings_calendar",
        "changes": "dividend_changes",
    }
    out: list[Call] = []
    for name in names:
        tool = next(t for prefix, t in tools.items() if name.startswith(f"call-{prefix}"))
        out.append(Call(tool=tool, arguments={}, result=tool_result(name)))
    return out


RESEARCHED = ("call-calendar-45.sse", "call-get-stock-pg.sse", "call-get-stock-ko.sse")
GATHERED = (
    "call-calendar-11.sse",
    "call-get-stock-aapl.sse",
    "call-get-stock-ibe.sse",
    "call-earnings-12.sse",
    "call-changes-7.sse",
)
EMPTY = WeekData(ex_dividends=[], earnings=[], dividend_changes=[])


def manifest(gathered: list[Call]) -> provenance.Manifest:
    return provenance.Manifest(provenance.Record(c.tool, c.result) for c in gathered)


@pytest.mark.parametrize(
    ("today", "start", "period"),
    [
        (date(2026, 10, 8), date(2026, 10, 12), "2026-W42"),  # a Thursday
        (date(2026, 10, 11), date(2026, 10, 12), "2026-W42"),  # Sunday: tomorrow's week
        (date(2026, 10, 12), date(2026, 10, 19), "2026-W43"),  # Monday: the next one
        # The ISO year isn't the calendar year at the edges: 2026 has 53 weeks,
        # and the week starting 2024-12-30 is the first of 2025.
        (date(2026, 12, 27), date(2026, 12, 28), "2026-W53"),
        (date(2024, 12, 29), date(2024, 12, 30), "2025-W01"),
    ],
)
def test_the_week_after(today: date, start: date, period: str) -> None:
    week = weekahead.week_after(today)
    assert (week.start, week.end.weekday(), week.period) == (start, 6, period)
    # Quantic's path: the ISO year, then the week, which the build checks.
    year, number = period.split("-")
    assert (week.slug, week.path) == (f"week-ahead-{number}", f"{year}/week-ahead-{number}")


def test_gather_takes_the_weeks_companies_from_the_tools() -> None:
    rows = weekahead.ex_dividends(WEEK, calls(*RESEARCHED))

    assert [(r.symbol, r.ex_dividend_date) for r in rows] == [
        ("PG", "2026-10-16"),
        ("KO", "2026-10-17"),
    ]
    pg = rows[0]
    assert (pg.name, pg.payment_frequency, pg.safety, pg.streak_years) == (
        "Procter & Gamble",
        "quarterly",
        "watch",
        28,
    )
    assert [r.code for r in pg.safety_reasons] == [
        "growing_dividend",
        "long_growth_streak",
        "tight_liquidity",
    ]
    assert pg.growth_ttm == 0.039728682170542484  # the ratio, unrounded
    # A calendar from before the rate, the yield and the pay date: absent is null.
    assert (pg.dividend_rate, pg.currency, pg.dividend_yield, pg.pay_date) == (None,) * 4


def test_gather_adds_the_weeks_earnings_and_the_dividend_changes() -> None:
    data = weekahead.gather(NEXT, calls(*GATHERED))

    assert [(r.symbol, r.ex_dividend_date) for r in data.ex_dividends] == [
        ("AAPL", "2026-10-19"),
        ("IBE.MC", "2026-10-20"),
    ]
    ibe = data.ex_dividends[1]
    # The calendar's 3.15 (%) as the ratio the post carries; the rate and the
    # pay date were null in Quantic when captured, and stay null.
    assert (ibe.currency, ibe.dividend_yield, ibe.dividend_rate, ibe.pay_date) == (
        "EUR",
        0.0315,
        None,
        None,
    )
    # The calendar asked for twelve days holds the rest of this week and
    # some of the one after; the post has its own week only.
    assert len(data.earnings) == 66
    assert {e.earnings_date for e in data.earnings} <= {f"2026-10-{day}" for day in range(19, 26)}
    iberdrola = next(e for e in data.earnings if e.symbol == "IBE.MC")
    assert (iberdrola.earnings_date, iberdrola.earnings_date_end, iberdrola.estimated) == (
        "2026-10-21",
        None,
        False,
    )
    assert data.dividend_changes == []  # the log started the day these were captured


def test_dividend_changes_are_copied_as_the_tool_has_them() -> None:
    # No raise or cut had been logged when the fixtures were captured (the log
    # started that day), so this result is written to the tool's shape, from
    # Quantic's lib/quantic_web/mcp/tools/dividend_changes.ex.
    changes = {
        "from": "2026-10-07",
        "to": "2026-10-14",
        "changes": [
            {
                "symbol": "VFC",
                "name": "V.F. Corporation",
                "sector": "Consumer Cyclical",
                "kind": "cut",
                "old_rate": 0.72,
                "new_rate": 0.36,
                "currency": "USD",
                "detected_on": "2026-10-08",
            }
        ],
    }
    gathered = [
        *calls(*GATHERED[:-1]),
        Call(tool="dividend_changes", arguments={"days": 7}, result=json.dumps(changes)),
    ]

    data = weekahead.gather(NEXT, gathered)

    # kind isn't carried: the page tells a raise from a cut by the rates.
    assert weekahead.data_block(data)["dividend_changes"] == [
        {
            "symbol": "VFC",
            "name": "V.F. Corporation",
            "sector": "Consumer Cyclical",
            "old_rate": 0.72,
            "new_rate": 0.36,
            "currency": "USD",
            "detected_on": "2026-10-08",
        }
    ]
    assert (
        provenance.check_data(
            weekahead.data_block(data), manifest(gathered), percentages=weekahead.PERCENTAGES
        )
        == []
    )


def test_every_value_in_the_data_traces_to_a_tool() -> None:
    gathered = calls(*GATHERED)
    data = weekahead.gather(NEXT, gathered)
    block = weekahead.data_block(data)

    def check(block: dict[str, Any]) -> list[str]:
        found = provenance.check_data(block, manifest(gathered), percentages=weekahead.PERCENTAGES)
        return [str(f) for f in found]

    assert check(block) == []

    # A value code changed on the way, as rounding would, is caught.
    rows = data.ex_dividends
    rounded = rows[0].model_copy(update={"growth_ttm": 0.0392})
    changed = data.model_copy(update={"ex_dividends": [rounded, rows[1]]})
    assert check(weekahead.data_block(changed)) == ["ex_dividends[0].growth_ttm = 0.0392"]

    # The yield is found as the percentage it was divided from, and only as that.
    assert block["ex_dividends"][0]["dividend_yield"] == 0.0032
    as_returned = rows[0].model_copy(update={"dividend_yield": 0.32})
    changed = data.model_copy(update={"ex_dividends": [as_returned, rows[1]]})
    assert check(weekahead.data_block(changed)) == ["ex_dividends[0].dividend_yield = 0.32"]
    unnamed = provenance.check_data(block, manifest(gathered))
    assert [f.path for f in unnamed] == [
        "ex_dividends[0].dividend_yield",
        "ex_dividends[1].dividend_yield",
    ]


def test_a_calendar_that_stops_short_of_the_week_is_not_enough() -> None:
    # 45 days from 2026-10-08 reach Sunday 2026-11-22, and Quantic's calendar
    # includes its last day (MarketData.stocks_with_ex_dividend_between): that
    # week is covered, the next one isn't.
    assert weekahead.ex_dividends(Week(date(2026, 11, 16)), calls(*RESEARCHED)) == []
    with pytest.raises(weekahead.IncompleteError, match="no dividend_calendar call covers"):
        weekahead.ex_dividends(Week(date(2026, 11, 23)), calls(*RESEARCHED))


@pytest.mark.parametrize(
    ("left_out", "error"),
    [
        ("call-earnings-12.sse", "no earnings_calendar call covers the week"),
        ("call-changes-7.sse", "no dividend_changes call succeeded"),
    ],
)
def test_the_weeks_earnings_and_changes_are_needed(left_out: str, error: str) -> None:
    with pytest.raises(weekahead.IncompleteError, match=error):
        weekahead.gather(NEXT, calls(*(name for name in GATHERED if name != left_out)))


def test_an_earnings_calendar_that_stops_short_of_the_week_is_not_enough() -> None:
    # Twelve days from 2026-10-14 reach 2026-10-26: the week after isn't covered.
    with pytest.raises(weekahead.IncompleteError, match="no earnings_calendar call covers"):
        weekahead.gather(Week(date(2026, 10, 26)), calls(*GATHERED))


def test_a_company_not_looked_up_is_named() -> None:
    with pytest.raises(weekahead.IncompleteError, match=r"not looked up with get_stock: KO$"):
        weekahead.ex_dividends(WEEK, calls("call-calendar-45.sse", "call-get-stock-pg.sse"))


def test_failed_calls_are_not_data() -> None:
    gathered = calls(*RESEARCHED)
    gathered[2].failed = True  # KO's lookup, as if it had been refused
    with pytest.raises(weekahead.IncompleteError, match="KO"):
        weekahead.ex_dividends(WEEK, gathered)


def test_a_week_with_no_companies_has_no_rows() -> None:
    # The week before PG's: nothing in the calendar falls in it.
    assert weekahead.ex_dividends(Week(date(2026, 10, 26)), calls(*RESEARCHED)) == []


def captured(name: str) -> quantic.Result:
    return quantic.Result(text=tool_result(name), is_error=False)


@pytest.mark.anyio
async def test_code_looks_up_the_weeks_companies_earnings_and_changes() -> None:
    stocks = {"AAPL": "call-get-stock-aapl.sse", "IBE.MC": "call-get-stock-ibe.sse"}
    server = FakeServer(
        results={
            "get_stock": lambda arguments: captured(stocks[arguments["symbol"]]),
            "earnings_calendar": captured("call-earnings-12.sse"),
            "dividend_changes": captured("call-changes-7.sse"),
        }
    )
    # The model's research is only the calendar.
    gathered = calls(GATHERED[0])

    await weekahead.look_up(server, NEXT, date(2026, 10, 14), gathered, gathered.append)

    # Each company of the week, in the calendar's order; then earnings through
    # Sunday the 25th, a day more for the server's UTC; then seven days back.
    assert server.received == [
        ("get_stock", {"symbol": "AAPL"}),
        ("get_stock", {"symbol": "IBE.MC"}),
        ("earnings_calendar", {"days": 12}),
        ("dividend_changes", {"days": 7}),
    ]
    assert not any(c.failed for c in gathered)
    data = weekahead.gather(NEXT, gathered)
    assert [e.symbol for e in data.ex_dividends] == ["AAPL", "IBE.MC"]
    assert len(data.earnings) == 66

    # Resumed, a call already made isn't made again.
    server.received.clear()
    await weekahead.look_up(server, NEXT, date(2026, 10, 14), gathered, gathered.append)
    assert server.received == []


@pytest.mark.anyio
async def test_a_company_already_looked_up_is_not_looked_up_again() -> None:
    server = FakeServer(
        results={
            "get_stock": captured("call-get-stock-ibe.sse"),
            "earnings_calendar": captured("call-earnings-12.sse"),
            "dividend_changes": captured("call-changes-7.sse"),
        }
    )
    # A run resumed after Apple's lookup: only Iberdrola is left.
    gathered = calls(*GATHERED[:2])

    await weekahead.look_up(server, NEXT, date(2026, 10, 14), gathered, gathered.append)

    assert [name for name, _ in server.received] == [
        "get_stock",
        "earnings_calendar",
        "dividend_changes",
    ]
    assert server.received[0] == ("get_stock", {"symbol": "IBE.MC"})


@pytest.mark.anyio
async def test_a_look_up_that_fails_is_recorded_then_raised() -> None:
    down = quantic.ToolServerUnavailableError("connection refused")
    server = FakeServer(results={"get_stock": down})
    gathered = calls(GATHERED[0])

    with pytest.raises(quantic.ToolServerUnavailableError):
        await weekahead.look_up(server, NEXT, date(2026, 10, 14), gathered, gathered.append)

    call = gathered[-1]
    assert (call.tool, call.arguments, call.failed, call.result) == (
        "get_stock",
        {"symbol": "AAPL"},
        True,
        "error: connection refused",
    )


PROSE = Prose(
    summary="Procter & Gamble and Coca-Cola go ex-dividend late in the week.",
    watch="Coca-Cola is rated safe, while Procter & Gamble is on watch for tight liquidity.",
)


@pytest.mark.anyio
async def test_the_writer_answers_in_the_prose_format() -> None:
    model = ScriptedModel([answers(PROSE.model_dump_json(), 100)])
    data = weekahead.gather(NEXT, calls(*GATHERED))

    written = await weekahead.write(model, NEXT, data)

    assert (written.prose, written.findings, written.attempts, written.tokens) == (
        PROSE,
        [],
        1,
        100,
    )
    assert model.formats == [weekahead.PROSE_FORMAT]
    system, user = model.shown[0]
    assert system.content == weekahead.WRITE_PROMPT
    # Shown the data, every company in it, under names with no figures in them.
    assert '"symbol": "IBE.MC"' in user.content
    assert '"long_term_growth": 0.02923938553006833' in user.content
    assert not any(name in user.content for name in ("cagr_5y", "growth_ttm", "streak_years"))
    assert "Monday 2026-10-19 to Sunday 2026-10-25" in user.content
    # And the week's earnings, and the raises and cuts (none, that week).
    assert '"earnings_date": "2026-10-21"' in user.content
    assert '"dividend_changes": []' in user.content


@pytest.mark.anyio
async def test_prose_with_figures_is_sent_back() -> None:
    model = ScriptedModel(
        [
            answers(json.dumps({"summary": "Two names go ex-dividend.", "watch": "Calm."}), 10),
            answers(PROSE.model_dump_json(), 20),
        ]
    )
    written = await weekahead.write(model, WEEK, EMPTY)

    assert (written.prose, written.findings, written.attempts, written.tokens) == (PROSE, [], 2, 30)
    retry = model.shown[1]
    # The rejected reply stays in the conversation, followed by what was wrong with it.
    assert json.loads(retry[2].content)["summary"] == "Two names go ex-dividend."
    assert "That prose has figures in it: 'Two'." in retry[3].content


@pytest.mark.anyio
async def test_wording_the_post_cant_use_is_sent_back_like_a_figure() -> None:
    # Run 4's summary (2026-10-14, the 27B), and a count in words.
    leaning = (
        "Apple and Iberdrola lead the weekly ex-dividend slate, offering distinct profiles "
        "for income-focused investors. Both pay quarterly or twice a year."
    )
    model = ScriptedModel(
        [
            answers(json.dumps({"summary": leaning, "watch": "Six raises were seen."}), 10),
            answers(PROSE.model_dump_json(), 20),
        ]
    )
    written = await weekahead.write(model, WEEK, EMPTY)

    assert (written.prose, written.findings, written.attempts) == (PROSE, [], 2)
    retry = model.shown[1][3].content
    # The figure and each phrase named, and what to do instead, once per rule.
    assert retry == (
        "That prose has figures in it: 'Six'. The post's tables show every figure, so the "
        "prose must have none. It has wording the post can't use: 'income-focused', "
        "'investors', 'Both'. Don't address the reader or name an audience: describe the "
        "companies. Don't count the companies, in any form: name them, or say \"these "
        'companies". Write both fields again without numbers, dates, counts or durations, in '
        "digits or in words."
    )


@pytest.mark.anyio
async def test_the_last_attempt_is_returned_with_its_figures() -> None:
    model = ScriptedModel(
        [answers(json.dumps({"summary": "A streak of 28 years.", "watch": "Calm."}))] * 3
    )
    written = await weekahead.write(model, WEEK, EMPTY)

    assert written.attempts == 3
    assert [str(f) for f in written.findings] == ["'28' (number 28)"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("Procter & Gamble goes ex-dividend.", "wasn't the prose as JSON"),
        ('{"summary": "Calm."}', "wasn't the prose as JSON"),
        ('{"summary": "Calm.", "watch": " "}', "left out watch"),
    ],
)
async def test_a_reply_that_isnt_prose(reply: str, error: str) -> None:
    model = ScriptedModel([answers(reply, 7)])
    with pytest.raises(weekahead.NotProseError, match=error) as caught:
        await weekahead.write(model, WEEK, EMPTY)
    assert caught.value.tokens == 7


SPANISH = Prose(
    summary="Procter & Gamble y Coca-Cola pasan a cotizar sin dividendo al final de la semana.",
    watch="Coca-Cola está calificada como segura, y Procter & Gamble en vigilancia por liquidez.",
)


@pytest.mark.anyio
async def test_a_translation_is_told_its_language_and_checked() -> None:
    model = ScriptedModel([answers(SPANISH.model_dump_json(), 50)])

    t = await weekahead.translate(model, PROSE, "es")

    assert (t.locale, t.prose, t.problems, t.tokens) == ("es", SPANISH, [], 50)
    system, user = model.shown[0]
    assert "into Spanish (Spain), in an informal register: tú, not usted." in system.content
    assert json.loads(user.content) == PROSE.model_dump()
    assert model.formats == [weekahead.PROSE_FORMAT]


def test_a_translation_with_figures_is_held() -> None:
    translated = SPANISH.model_copy(update={"summary": SPANISH.summary + " Son 2 empresas."})
    assert weekahead.check_translation(PROSE, translated) == ["summary: figure '2'"]


def test_a_translation_far_from_the_englishs_length_is_held() -> None:
    short = SPANISH.model_copy(update={"watch": "Segura."})
    [problem] = weekahead.check_translation(PROSE, short)
    assert problem.startswith("watch: 0.09 times as long as the English, outside 0.75-1.75")


@pytest.mark.anyio
async def test_a_translation_that_isnt_prose_is_held_as_it_came() -> None:
    model = ScriptedModel([answers("Lo siento, no puedo.", 5)])
    t = await weekahead.translate(model, PROSE, "fr")
    assert (t.prose, t.raw, t.tokens) == (None, "Lo siento, no puedo.", 5)
    assert t.problems[0].startswith("the reply wasn't the prose as JSON")


def test_a_post_file_reads_back_as_it_was_checked() -> None:
    data = weekahead.gather(NEXT, calls(*GATHERED))
    block = weekahead.data_yaml(data)

    text = weekahead.render(NEXT, 7, "es", block, SPANISH)

    assert text.startswith('---\nkind: "week_ahead"\nperiod: "2026-W43"\nlocale: "es"\n')
    assert '    ex_dividend_date: "2026-10-20"\n' in text
    assert "    dividend_yield: 0.0315\n    pay_date: null\n" in text
    assert '  earnings:\n  - symbol: "' in text
    assert "  dividend_changes: []\n" in text
    assert "## La semana que viene\n\n" + SPANISH.summary in text
    assert weekahead.check_file(text, "es", data, SPANISH) == []
    front, sections = weekahead.read_back(text, "es")
    assert (front["run_id"], front["fold_after"], front["sections"]) == (
        7,
        "summary",
        ["summary", "watch"],
    )
    assert sections == SPANISH.model_dump()


def test_every_locale_carries_the_same_data_block() -> None:
    block = weekahead.data_yaml(weekahead.gather(NEXT, calls(*GATHERED)))
    files = [weekahead.render(NEXT, 7, locale, block, PROSE) for locale in weekahead.LOCALES]
    assert all(block in f for f in files)
    assert len(files) == 7


def test_strings_are_quoted_whatever_they_look_like() -> None:
    # "ON" is a boolean to a YAML 1.1 parser, and 1E3 a number to a YAML 1.2
    # one; PyYAML would leave the second bare. Quoted, both stay strings.
    data = weekahead.gather(NEXT, calls(*GATHERED))
    rows = data.ex_dividends
    odd = data.model_copy(
        update={
            "ex_dividends": [
                r.model_copy(update={"symbol": s}) for r, s in zip(rows, ["ON", "1E3"], strict=True)
            ]
        }
    )
    block = weekahead.data_yaml(odd)
    assert 'symbol: "ON"' in block
    assert 'symbol: "1E3"' in block
    text = weekahead.render(NEXT, 7, "en", block, PROSE)
    assert weekahead.check_file(text, "en", odd, PROSE) == []


def test_prose_that_breaks_the_file_is_caught() -> None:
    data = weekahead.gather(NEXT, calls(*GATHERED))
    headed = PROSE.model_copy(update={"watch": "Calm.\n\n## Buy now\n\nIt goes up."})

    text = weekahead.render(NEXT, 7, "en", weekahead.data_yaml(data), headed)

    assert weekahead.check_file(text, "en", data, headed) == [
        "the file doesn't read back: an unexpected heading: '## Buy now'"
    ]


def test_a_data_block_that_reads_back_differently_is_caught() -> None:
    data = weekahead.gather(NEXT, calls(*GATHERED))
    text = weekahead.render(NEXT, 7, "en", weekahead.data_yaml(data), PROSE)
    tampered = text.replace("estimated: false", "estimated: true", 1)
    assert weekahead.check_file(tampered, "en", data, PROSE) == [
        "the file's data block doesn't read back as the data"
    ]
    assert yaml.safe_load(tampered.split("---\n")[1])["locale"] == "en"


def test_the_package_ships_its_prompts_and_locales() -> None:
    assert list(weekahead.LOCALES) == ["en", "es", "ca", "fr", "de", "it", "pt"]
    for locale in weekahead.LOCALES.values():
        assert set(locale.headings) == set(weekahead.SECTIONS)
    assert "$language" in weekahead.TRANSLATE_PROMPT.template
    assert "No figures at all" in weekahead.WRITE_PROMPT


def test_the_question_says_what_today_is() -> None:
    # The calendar counts days from today: a model must know today to ask for enough.
    assert weekahead.question(date(2026, 10, 8)).startswith(
        "Today is Thursday 2026-10-08. Gather the data for the Dividend Week Ahead, "
        "for the week from Monday 2026-10-12 to Sunday 2026-10-18:"
    )


@pytest.mark.parametrize(
    ("today", "days"),
    [
        (date(2026, 10, 5), 13),
        (date(2026, 10, 8), 10),
        (date(2026, 10, 9), 9),
        (date(2026, 10, 11), 7),
    ],
)
def test_the_question_says_how_far_away_sunday_is(today: date, days: int) -> None:
    # Told only the date, the model asked for 7 days from a Friday: 2 short.
    assert weekahead.question(today).endswith(f"Sunday 2026-10-18 is {days} days from today.")


def test_an_iso_week_names_its_monday() -> None:
    assert weekahead.parse_week("2026-W44") == weekahead.Week(date(2026, 10, 26))
    assert weekahead.parse_week("2026-w44").period == "2026-W44"
    # The ISO year: 2026-W53 starts in December, 2027-W01 may start in 2027.
    assert weekahead.parse_week("2026-W53").start == date(2026, 12, 28)


@pytest.mark.parametrize("text", ["2026-44", "W44", "2026-W54", "2026-Wx", ""])
def test_anything_else_is_not_a_week(text: str) -> None:
    with pytest.raises(ValueError, match=r"ISO week|week|year"):
        weekahead.parse_week(text)


def test_a_week_can_be_written_from_its_monday_but_not_after() -> None:
    w44 = weekahead.parse_week("2026-W44")
    assert weekahead.can_write(w44, date(2026, 10, 25))
    assert weekahead.can_write(w44, date(2026, 10, 26))
    # From Tuesday the calendar would miss Monday.
    assert not weekahead.can_write(w44, date(2026, 10, 27))


@dataclass
class _Run:
    started_at: datetime
    week_start: date | None = None


def test_a_runs_week_is_the_one_asked_for_or_else_the_week_after_it_started() -> None:
    monday = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    assert weekahead.week_of(_Run(monday)).period == "2026-W45"
    assert weekahead.week_of(_Run(monday, date(2026, 10, 26))).period == "2026-W44"


def test_the_question_names_the_week_asked_for() -> None:
    w44 = weekahead.parse_week("2026-W44")
    assert weekahead.question(date(2026, 10, 26), w44) == (
        "Today is Monday 2026-10-26. Gather the data for the Dividend Week Ahead, "
        "for the week from Monday 2026-10-26 to Sunday 2026-11-01: get the dividend "
        "calendar that covers every day of that week. Each company in it is looked up for "
        "you afterwards. Sunday 2026-11-01 is 6 days from today."
    )


def test_a_companys_name_in_the_prose_isnt_read_as_advice() -> None:
    # A company named like an advice word: "Best Buy" (the X posts, 2026-10-28).
    data = weekahead.gather(NEXT, calls(*GATHERED))
    renamed = data.model_copy(
        update={
            "ex_dividends": [data.ex_dividends[0].model_copy(update={"name": "Best Buy Co., Inc."})]
        }
    )
    prose = Prose(summary="Best Buy goes ex-dividend this week.", watch="Best Buy is rated safe.")
    assert weekahead.check_prose(prose) != []  # without the names, "Buy" is advice
    assert weekahead.check_prose(prose, weekahead.names(renamed)) == []
