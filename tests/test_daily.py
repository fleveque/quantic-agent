import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

import pytest
from conftest import tool_result
from test_agent import ScriptedModel, answers

from quantic_agent import daily, provenance, quantic
from quantic_agent.agent import Call

# Wednesday 2026-10-28, when the fixtures were captured from quantic.finance.
TODAY = date(2026, 10, 28)
FIRST = ("call-changes-3.sse", "call-calendar-3.sse", "call-screen-safe-streak.sse")


def first_calls() -> list[Call]:
    return [
        Call(tool, arguments, tool_result(name))
        for (tool, arguments), name in zip(daily.first_calls(), FIRST, strict=True)
    ]


@dataclass
class Stocks:
    """Answers get_stock from the captured fixtures, by symbol: 1052.HK is
    call-get-stock-1052-hk.sse."""

    asked: list[str] = field(default_factory=lambda: list[str]())

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> quantic.Result:
        symbol: str = arguments["symbol"]
        self.asked.append(symbol)
        fixture = f"call-get-stock-{symbol.lower().replace('.', '-')}.sse"
        return quantic.Result(text=tool_result(fixture), is_error=False)


def looked_up() -> tuple[list[tuple[daily.Candidate, daily.Stock]], list[daily.Rejected], Stocks]:
    server = Stocks()
    chosen = daily.candidates(first_calls(), TODAY, set())
    accepted, rejected = asyncio.run(daily.look_up(server, chosen, lambda _: None))
    return accepted, rejected, server


def facts_of(symbol: str) -> daily.Facts:
    accepted, _, _ = looked_up()
    candidate, stock = next((c, s) for c, s in accepted if c.symbol == symbol)
    return daily.facts(candidate, stock, TODAY)


# ---- choosing ----------------------------------------------------------------


def test_each_angle_has_its_candidates_best_first() -> None:
    chosen = daily.candidates(first_calls(), TODAY, set())
    assert {angle: [c.symbol for c in cs] for angle, cs in chosen.items()} == {
        # The largest changes of 1% or more: KMI's 0.8% isn't one, and RY6.MU
        # and DNLML.XC are secondary listings.
        daily.Angle.CHANGE: ["A17U.SI", "ITRK.L", "WDC", "BRX", "BA.L", "REPX"],
        # Thursday's and Friday's, the highest yields up to 8%: PSEC's 27.1%
        # and AGNC's 16.23% are left out, and today's are past.
        daily.Angle.EX_DIVIDEND: ["1052.HK", "EPR", "O", "TGS.OL", "SKT", "NI"],
        # Furthest above their own 5-year average; MDO.DE and MDO.F, Frankfurt
        # listings of McDonald's, are left out.
        daily.Angle.YIELD: ["NKE", "DPZ", "BF-B", "MKTX", "DKS", "GGG"],
    }


def test_a_company_proposed_lately_isnt_a_candidate() -> None:
    chosen = daily.candidates(first_calls(), TODAY, {"NKE", "BA.L"})
    assert [c.symbol for c in chosen[daily.Angle.YIELD]][:1] == ["DPZ"]
    assert "BA.L" not in [c.symbol for c in chosen[daily.Angle.CHANGE]]


def test_a_company_is_a_candidate_for_one_angle_only() -> None:
    # REPX is a raise and goes ex-dividend today; WDC a raise. Were one also
    # a high yield, it would be looked at as the change only.
    chosen = daily.candidates(first_calls(), TODAY, set())
    symbols = [c.symbol for cs in chosen.values() for c in cs]
    assert len(symbols) == len(set(symbols))


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 28), [date(2026, 10, 29), date(2026, 10, 30)]),  # Wednesday
        (date(2026, 10, 30), [date(2026, 11, 2), date(2026, 11, 3)]),  # Friday: Monday, Tuesday
    ],
)
def test_the_next_weekdays(today: date, expected: list[date]) -> None:
    assert daily.next_weekdays(today, 2) == expected


def test_each_angle_is_looked_up_until_one_company_is_accepted() -> None:
    accepted, rejected, server = looked_up()
    assert [c.symbol for c, _ in accepted] == ["BA.L", "O", "NKE"]
    assert server.asked == ["A17U.SI", "ITRK.L", "WDC", "BRX", "BA.L", "1052.HK", "EPR", "O", "NKE"]
    assert [(r.symbol, r.reason) for r in rejected] == [
        ("A17U.SI", "a raise with a streak of 0 years, under 5"),
        ("ITRK.L", "a cut next to a running streak of 3 years: the data contradicts itself"),
        ("WDC", "a raise with a streak of 0 years, under 5"),
        ("BRX", "a raise with a streak of 4 years, under 5"),
        ("1052.HK", "a streak of 0 years, under 10"),
        ("EPR", "a streak of 2 years, under 10"),
    ]


# ---- the facts ---------------------------------------------------------------


def test_every_copied_value_is_one_a_tool_returned() -> None:
    accepted, _, server = looked_up()
    calls = first_calls() + [
        Call(
            "get_stock",
            {"symbol": s},
            tool_result(f"call-get-stock-{s.lower().replace('.', '-')}.sse"),
        )
        for s in server.asked
    ]
    manifest = provenance.Manifest([provenance.Record(c.tool, c.result) for c in calls])
    for candidate, stock in accepted:
        assert provenance.check_data(daily.facts(candidate, stock, TODAY).copied, manifest) == []


def test_why_the_yield_is_high_is_given_when_the_price_explains_most_of_it() -> None:
    nike = facts_of("NKE").derived
    assert nike["current_yield_times_5y_average"] == 3.1
    assert nike["last_full_year_times_its_5y_average"] == 1.18
    assert nike["why_the_yield_is_high"].startswith(
        "The yield is above its 5-year average mostly because the share price fell"
    )
    # Realty Income's yield is 1.14 times its average: no cause to give.
    assert "why_the_yield_is_high" not in facts_of("O").derived


def test_amounts_in_different_units_are_left_out() -> None:
    # BAE's last price is 20.17 GBP; its 5-year high (2187.0) and its dividend
    # history (34.1 in 2025) are in pence. Shown, "99.1% below its high".
    bae = facts_of("BA.L")
    assert "price_high_monthly_5y" not in bae.copied
    assert "price_below_5y_high_pct" not in bae.derived
    assert "dividend_per_share_last_full_year" not in bae.copied
    # Ratios within one series hold in any unit.
    assert bae.derived["last_full_year_times_first_year"] == 1.68
    # Nike's are all dollars.
    assert facts_of("NKE").derived["price_below_5y_high_pct"] == 77.8


def test_the_next_ex_dividend_month_is_after_today() -> None:
    assert facts_of("NKE").derived["next_ex_dividend_month"] == "December"
    assert facts_of("BA.L").derived["next_ex_dividend_month"] == "April"  # April and October
    realty = facts_of("O").derived
    assert realty["next_ex_dividend_month"] == "November"
    assert "goes_ex_dividend_in" not in realty  # every month says nothing


def months_of(symbol: str, **profile: object) -> dict[str, object]:
    accepted, _, _ = looked_up()
    candidate, stock = next((c, s) for c, s in accepted if c.symbol == symbol)
    changed = stock.profile.model_copy(update=profile)
    return daily.facts(candidate, stock.model_copy(update={"profile": changed}), TODAY).derived


def test_months_with_no_real_payments_are_never_called_payments() -> None:
    # Quantic before #533 gives no basis; after it, "ex_dividend" and ex_months.
    for profile in ({}, {"payment_months_basis": "ex_dividend", "ex_months": [3, 9]}):
        derived = months_of("NKE", **profile)
        assert "pays_in" not in derived
        assert "next_payment_month" not in derived
    assert derived["goes_ex_dividend_in"] == ["March", "September"]


def test_real_payment_months_are_called_payments() -> None:
    derived = months_of(
        "NKE", payment_months_basis="paid", payment_months=[1, 7], ex_months=[6, 12]
    )
    assert derived["pays_in"] == ["January", "July"]
    assert derived["next_payment_month"] == "January"
    assert "goes_ex_dividend_in" not in derived


def test_a_change_is_sized_by_code() -> None:
    assert {
        k: facts_of("BA.L").derived[k] for k in ("change", "change_pct", "change_size_pct")
    } == {
        "change": "raise",
        "change_pct": 5.6,
        "change_size_pct": 5.6,
    }


def test_a_payment_change_is_named_as_one_payment() -> None:
    # BAE pays twice a year; since quantic#526 its change is one payment
    # against the same payment a year earlier, not an annual rate.
    accepted, _, _ = looked_up()
    candidate, stock = next((c, s) for c, s in accepted if c.symbol == "BA.L")
    assert candidate.change is not None
    payment = replace(candidate, change=candidate.change.model_copy(update={"basis": "payment"}))

    copied = daily.facts(payment, stock, TODAY).copied

    assert "old_annual_rate" not in copied
    assert (copied["same_payment_a_year_earlier"], copied["new_payment"]) == (
        candidate.change.old_rate,
        candidate.change.new_rate,
    )
    assert "old_annual_rate" in facts_of("BA.L").copied


def test_facts_read_back_as_they_were_stored() -> None:
    nike = facts_of("NKE")
    assert daily.Facts.from_json(json.loads(json.dumps(nike.as_json()))) == nike


# ---- checking a version --------------------------------------------------------

# Written by the 27B for these facts on 2026-10-28, and passed.
NIKE = (
    "💵 Nike ($NKE) yield is 4.37%, while the dividend is only 1.18 times its 5-year average. "
    "The price drop explains the gap.\n\n🔍 Last price 37.56 on Oct 28. Dividend has risen for "
    "23 years."
)


def test_a_version_that_keeps_the_rules_passes() -> None:
    assert daily.check_version(NIKE, facts_of("NKE"), TODAY) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        # Each, from what the 27B wrote in the experiment or here, or a rule's case.
        (NIKE.replace("4.37%", "4.4%"), "a figure not in the data: '4.4%'"),
        (NIKE.replace("37.56", "56.82"), "a figure not in the data: '56.82'"),  # Realty Income's
        (NIKE.replace("The price", "Investors see the price"), "wording (audience)"),
        (NIKE.replace("explains the gap", "is significant"), "selling language"),
        (NIKE.replace("5-year average", "5y avg"), "not plain words: '5y'"),
        (NIKE.replace("Last price", "Nike trades at"), "the price is the last one Quantic saw"),
        (NIKE.replace(" Nike ($NKE)", " $NKE").replace("$NKE", "It"), "doesn't name the company"),
        (NIKE.replace("years.", "years!"), "an exclamation mark"),
        (NIKE + " #dividends", "a hashtag"),
        (NIKE.replace("Dividend", "DIVIDEND"), "a word in capitals: DIVIDEND"),
        (NIKE.replace("($NKE)", "($NKE, $NKE)"), "the cashtag $NKE must appear exactly once"),
        (
            NIKE.replace("🔍 Last price", "Last price").replace("23 years.", "23 years. 🔍"),
            "doesn't open its paragraph",
        ),
        (NIKE.replace("💵 ", "🚀 "), "one or two emojis from the list"),
        (NIKE.replace("4.37%", "4.37% in 2026, 38p"), "a unit glued to it: '38p'"),
        (NIKE + " " + "x" * 80, "too long"),
        (NIKE.replace("Nike", "Northwind"), "the prompt's example company"),
    ],
)
def test_what_a_version_cant_do(text: str, problem: str) -> None:
    assert any(problem in p for p in daily.check_version(text, facts_of("NKE"), TODAY))


def test_a_cause_is_given_only_when_the_data_states_one() -> None:
    # Realty Income's facts have no why_the_yield_is_high: "reflecting 28
    # straight years of increases" was made up (2026-10-28).
    text = (
        "📊 Realty Income ($O) yields 5.74%, slightly above its 5-year average, reflecting 28 "
        "straight years of increases."
    )
    assert daily.check_version(text, facts_of("O"), TODAY) == [
        "a cause: 'reflecting'; the data gives none, so describe without explaining"
    ]
    # Nike's has one: the same word is allowed.
    assert daily.check_version(NIKE, facts_of("NKE"), TODAY) == []


def test_a_company_x_makes_no_cashtag_of_is_named_without_one() -> None:
    bae = facts_of("BA.L")
    assert bae.cashtag is None
    text = "📈 BAE Systems raised its annual rate 5.6% to 0.38 GBP, seen on Oct 25."
    assert daily.check_version(text, bae, TODAY) == []
    assert daily.check_version(text.replace("BAE Systems", "$BA"), bae, TODAY)[-1:] == [
        "no cashtag: X doesn't make one of BA.L"
    ]


def test_a_company_name_isnt_advice() -> None:
    # The wording rules see "Buy" in "Best Buy" only outside a company's name.
    bae = daily.Facts(daily.Angle.CHANGE, "BBY", "Best Buy Co., Inc.", {}, {})
    assert not any(
        "advice" in p for p in daily.check_version("📈 Best Buy ($BBY) keeps raising.", bae, TODAY)
    )


# ---- writing -------------------------------------------------------------------


def reply(*versions: str, tokens: int = 10) -> Any:
    return answers(json.dumps({"versions": list(versions)}), tokens)


GOOD = [
    NIKE,
    "📉 Nike ($NKE) yields 4.37%, 3.1 times its 5-year average.\n\n👟 Mostly because the share "
    "price fell.",
    "👟 Nike ($NKE) has raised its dividend for 23 years.\n\n💵 Its yield is 4.37%.",
]


def test_versions_that_pass_are_proposed_at_once() -> None:
    model = ScriptedModel([reply(*GOOD)])
    written = asyncio.run(daily.write(model, facts_of("NKE"), TODAY))
    assert (written.attempts, [v.text for v in written.ready]) == (1, GOOD)
    # The writer is asked for JSON in the versions' format, told the date,
    # and given the cashtag to use.
    [conversation] = model.shown
    assert model.formats == [daily.VERSIONS_FORMAT]
    assert conversation[1].content.startswith("Today is Wednesday 2026-10-28.")
    assert "Include the cashtag $NKE once" in conversation[0].content


def test_a_version_that_fails_is_sent_back_and_one_that_passed_is_kept() -> None:
    bad = GOOD[2] + "!"
    model = ScriptedModel([reply(GOOD[0], GOOD[1], bad), reply(GOOD[0], "📈 Nike!", GOOD[2])])
    written = asyncio.run(daily.write(model, facts_of("NKE"), TODAY))
    assert written.attempts == 2
    assert [v.text for v in written.ready] == GOOD
    assert written.tokens == 20
    sent_back = model.shown[1][-1].content
    assert sent_back.startswith("Some versions break the rules:\nVersion 3: an exclamation mark")
    assert "Reply with all 3 versions again" in sent_back


def test_after_the_last_attempt_what_still_fails_is_held() -> None:
    model = ScriptedModel([reply(GOOD[0], "📈 Nike!", "x")] * 3)
    written = asyncio.run(daily.write(model, facts_of("NKE"), TODAY))
    assert written.attempts == 3
    assert [v.text for v in written.ready] == [GOOD[0]]
    assert [v.text for v in written.versions if not v.ready] == ["📈 Nike!", "x"]


def test_no_more_versions_are_proposed_than_asked_for() -> None:
    model = ScriptedModel(
        [reply(GOOD[0], GOOD[1], "x"), reply(GOOD[2], "📈 Nike ($NKE) pays in December.", "y")]
    )
    written = asyncio.run(daily.write(model, facts_of("NKE"), TODAY))
    assert len(written.ready) == 3


def test_a_reply_that_isnt_the_versions_is_an_error() -> None:
    model = ScriptedModel([answers("Here are some posts.", 5)])
    with pytest.raises(daily.NotPostsError) as err:
        asyncio.run(daily.write(model, facts_of("NKE"), TODAY))
    assert err.value.tokens == 5


def test_the_prompt_reads_with_its_example() -> None:
    # A $ in the prompt file is a placeholder unless written $$: the example's
    # cashtag once stopped every run with KeyError.
    text = daily.prompt(3, None)
    assert "📈 Northwind ($NWND) now yields 3.2%" in text
    assert "No cashtag: X doesn't make one of this company's ticker." in text


# ---- the issue -------------------------------------------------------------------


def written_for_the_day() -> tuple[list[daily.Written], list[daily.Rejected]]:
    _, rejected, _ = looked_up()
    nike = daily.Written(
        facts_of("NKE"),
        [daily.Version(GOOD[0]), daily.Version(GOOD[2]), daily.Version("x", ["held"])],
        2,
        0,
    )
    bae = daily.Written(facts_of("BA.L"), [daily.Version("y", ["held"])], 3, 0)
    return [nike, bae], rejected


def test_the_issue_has_each_proposed_version_with_its_box_and_link() -> None:
    written, rejected = written_for_the_day()
    body = daily.issue_body(TODAY, 7, written, rejected)
    assert body.startswith("Drafted by quantic-agent from Quantic's data on 2026-10-28 (run 7:")
    assert "## Nike, Inc. (NKE): its yield against its own history" in body
    assert (
        f"- [ ] posted NKE version 2\n\n```text\n{GOOD[2]}\n\nhttps://quantic.finance/stocks/NKE\n```"
        in body
    )
    assert "posted NKE version 3" not in body  # held
    assert '"why_the_yield_is_high": "The yield is above' in body
    assert (
        "- BAE SYSTEMS PLC ORD 2.5P (BA.L): no version passed the checks after 3 attempts" in body
    )
    assert (
        "- INTERTEK GROUP PLC ORD 1P (ITRK.L), a dividend change: a cut next to a running streak "
        "of 3 years: the data contradicts itself"
    ) in body


def test_ticks_are_read_back_from_the_issue() -> None:
    written, rejected = written_for_the_day()
    body = daily.issue_body(TODAY, 7, written, rejected)
    assert daily.ticks(body) == set()
    ticked = body.replace("- [ ] posted NKE version 2", "- [x] posted NKE version 2")
    assert daily.ticks(ticked) == {("NKE", 2)}
    # GitHub writes an X in capitals when the box is ticked in some clients.
    assert daily.ticks(ticked.replace("[x]", "[X]")) == {("NKE", 2)}


def test_the_title_names_the_day() -> None:
    assert daily.title(TODAY) == "X posts for Wednesday 2026-10-28"
