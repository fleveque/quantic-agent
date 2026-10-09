import json
from datetime import date

import pytest
import yaml
from conftest import tool_result
from test_agent import ScriptedModel, answers

from quantic_agent import provenance, weekahead
from quantic_agent.agent import Call
from quantic_agent.weekahead import Prose, Week

# The week after Thursday 2026-10-08, when the fixtures were captured: Procter
# & Gamble and Coca-Cola go ex-dividend in it.
WEEK = Week(date(2026, 10, 12))


def calls(*names: str) -> list[Call]:
    """Successful calls answered by captured tools/call replies."""
    tools = {"calendar": "dividend_calendar", "get-stock": "get_stock"}
    out: list[Call] = []
    for name in names:
        tool = next(t for prefix, t in tools.items() if name.startswith(f"call-{prefix}"))
        out.append(Call(tool=tool, arguments={}, result=tool_result(name)))
    return out


RESEARCHED = ("call-calendar-45.sse", "call-get-stock-pg.sse", "call-get-stock-ko.sse")


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
    assert week.slug == f"week-ahead-{period}"


def test_gather_takes_the_weeks_companies_from_the_tools() -> None:
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))

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


def test_every_value_in_the_data_traces_to_a_tool() -> None:
    gathered = calls(*RESEARCHED)
    rows = weekahead.gather(WEEK, gathered)
    assert provenance.check_data(weekahead.data_block(rows), manifest(gathered)) == []

    # A value code changed on the way, as rounding would, is caught.
    rounded = rows[0].model_copy(update={"growth_ttm": 0.0397})
    found = provenance.check_data(weekahead.data_block([rounded, rows[1]]), manifest(gathered))
    assert [str(f) for f in found] == ["ex_dividends[0].growth_ttm = 0.0397"]


def test_a_calendar_that_stops_short_of_the_week_is_not_enough() -> None:
    # 45 days from 2026-10-08 reach Sunday 2026-11-22, and Quantic's calendar
    # includes its last day (MarketData.stocks_with_ex_dividend_between): that
    # week is covered, the next one isn't.
    assert weekahead.gather(Week(date(2026, 11, 16)), calls(*RESEARCHED)) == []
    with pytest.raises(weekahead.IncompleteError, match="no dividend_calendar call covers"):
        weekahead.gather(Week(date(2026, 11, 23)), calls(*RESEARCHED))


def test_a_company_not_looked_up_is_named() -> None:
    with pytest.raises(weekahead.IncompleteError, match=r"not looked up with get_stock: KO$"):
        weekahead.gather(WEEK, calls("call-calendar-45.sse", "call-get-stock-pg.sse"))


def test_failed_calls_are_not_data() -> None:
    gathered = calls(*RESEARCHED)
    gathered[2].failed = True  # KO's lookup, as if it had been refused
    with pytest.raises(weekahead.IncompleteError, match="KO"):
        weekahead.gather(WEEK, gathered)


def test_a_week_with_no_companies_has_no_rows() -> None:
    # The week before PG's: nothing in the calendar falls in it.
    assert weekahead.gather(Week(date(2026, 10, 26)), calls(*RESEARCHED)) == []


PROSE = Prose(
    summary="Procter & Gamble and Coca-Cola go ex-dividend late in the week.",
    watch="Coca-Cola is rated safe, while Procter & Gamble is on watch for tight liquidity.",
)


@pytest.mark.anyio
async def test_the_writer_answers_in_the_prose_format() -> None:
    model = ScriptedModel([answers(PROSE.model_dump_json(), 100)])
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))

    written = await weekahead.write(model, WEEK, rows)

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
    assert '"symbol": "KO"' in user.content
    assert '"long_term_growth": 0.044617420086995985' in user.content
    assert not any(name in user.content for name in ("cagr_5y", "growth_ttm", "streak_years"))
    assert "Monday 2026-10-12 to Sunday 2026-10-18" in user.content


@pytest.mark.anyio
async def test_prose_with_figures_is_sent_back() -> None:
    model = ScriptedModel(
        [
            answers(json.dumps({"summary": "Two names go ex-dividend.", "watch": "Calm."}), 10),
            answers(PROSE.model_dump_json(), 20),
        ]
    )
    written = await weekahead.write(model, WEEK, [])

    assert (written.prose, written.findings, written.attempts, written.tokens) == (PROSE, [], 2, 30)
    retry = model.shown[1]
    # The rejected reply stays in the conversation, followed by what was wrong with it.
    assert json.loads(retry[2].content)["summary"] == "Two names go ex-dividend."
    assert "That prose has figures in it: 'Two'." in retry[3].content


@pytest.mark.anyio
async def test_the_last_attempt_is_returned_with_its_figures() -> None:
    model = ScriptedModel(
        [answers(json.dumps({"summary": "A streak of 28 years.", "watch": "Calm."}))] * 3
    )
    written = await weekahead.write(model, WEEK, [])

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
        await weekahead.write(model, WEEK, [])
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
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))
    data = weekahead.data_yaml(rows)

    text = weekahead.render(WEEK, 7, "es", data, SPANISH)

    assert text.startswith('---\nkind: "week_ahead"\nperiod: "2026-W42"\nlocale: "es"\n')
    assert '    ex_dividend_date: "2026-10-16"\n' in text
    assert "## La semana que viene\n\n" + SPANISH.summary in text
    assert weekahead.check_file(text, "es", rows, SPANISH) == []
    front, sections = weekahead.read_back(text, "es")
    assert (front["run_id"], front["fold_after"], front["sections"]) == (
        7,
        "summary",
        ["summary", "watch"],
    )
    assert sections == SPANISH.model_dump()


def test_every_locale_carries_the_same_data_block() -> None:
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))
    data = weekahead.data_yaml(rows)
    files = [weekahead.render(WEEK, 7, locale, data, PROSE) for locale in weekahead.LOCALES]
    assert all(data in f for f in files)
    assert len(files) == 7


def test_strings_are_quoted_whatever_they_look_like() -> None:
    # "ON" is a boolean to a YAML 1.1 parser, and 1E3 a number to a YAML 1.2
    # one; PyYAML would leave the second bare. Quoted, both stay strings.
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))
    odd = [r.model_copy(update={"symbol": s}) for r, s in zip(rows, ["ON", "1E3"], strict=True)]
    data = weekahead.data_yaml(odd)
    assert 'symbol: "ON"' in data
    assert 'symbol: "1E3"' in data
    text = weekahead.render(WEEK, 7, "en", data, PROSE)
    assert weekahead.check_file(text, "en", odd, PROSE) == []


def test_prose_that_breaks_the_file_is_caught() -> None:
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))
    data = weekahead.data_yaml(rows)
    headed = PROSE.model_copy(update={"watch": "Calm.\n\n## Buy now\n\nIt goes up."})

    text = weekahead.render(WEEK, 7, "en", data, headed)

    assert weekahead.check_file(text, "en", rows, headed) == [
        "the file doesn't read back: an unexpected heading: '## Buy now'"
    ]


def test_a_data_block_that_reads_back_differently_is_caught() -> None:
    rows = weekahead.gather(WEEK, calls(*RESEARCHED))
    text = weekahead.render(WEEK, 7, "en", weekahead.data_yaml(rows), PROSE)
    tampered = text.replace("streak_years: 28", "streak_years: 29", 1)
    assert weekahead.check_file(tampered, "en", rows, PROSE) == [
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
