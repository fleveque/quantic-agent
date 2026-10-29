import pytest

from quantic_agent import wording
from quantic_agent.provenance import Kind

# Real prose. Run 4 (2026-10-14, the 27B) and the milestone 11 post (the 9B)
# leaned towards advice or counted the companies; runs 2 and 3, the second
# published as quantic#492, didn't.
RUN_4 = (
    "Apple and Iberdrola lead the weekly ex-dividend slate, offering distinct profiles for "
    "income-focused investors. Meanwhile, Cleveland-Cliffs is expected to report earnings "
    "alongside a heavy slate of other major names, adding a layer of corporate news that may "
    "influence sentiment around the week's ex-dividend dates."
)
MILESTONE_11 = (
    "This week features companies that have both sustained a very long history of increases. "
    "While one maintains a robust safety profile, the other balances its strong track record "
    "against signs of constrained liquidity."
)
PUBLISHED = (
    "Apple leads off the week with a quarterly payment, supported by a long record of "
    "consecutive raises and a safety status that reflects its growing dividend. Iberdrola "
    "follows with a semi-annual payment, carrying a watch status due to tight liquidity despite "
    "its own streak of increasing payouts.\n\nIberdrola presents an interesting contrast as it "
    "combines a recent acceleration in dividend growth compared to its longer-term average with "
    "a warning on liquidity, while also reporting earnings during the same week. Apple, by "
    "comparison, maintains a strong safe classification with recent growth that has slightly "
    "trailed its longer-term trend."
)
RUN_2 = (
    "Apple and Iberdrola are the companies going ex-dividend this week. Apple carries a safe "
    "safety status supported by a growing dividend and a long growth streak, while Iberdrola is "
    "flagged to watch due to tight liquidity despite a growing dividend.\n\nApple shows a long "
    "growth streak with recent growth slightly below its long-term trend. No dividend changes "
    "are recorded, and several companies, including Netflix, IBM, and Tesla, are expected to "
    "report earnings in the coming week."
)


def found(text: str) -> list[tuple[str, str]]:
    return [(f.text, f.value) for f in wording.check(text)]


def test_what_run_4_published_would_have_been_held() -> None:
    assert found(RUN_4) == [
        ("income-focused", "audience"),
        ("investors", "audience"),
        ("sentiment", "market"),
    ]


def test_counting_in_words_the_figure_check_doesnt_read() -> None:
    assert found(MILESTONE_11) == [("both", "count"), ("one", "count")]


@pytest.mark.parametrize("text", [PUBLISHED, RUN_2])
def test_prose_that_describes_the_data_passes(text: str) -> None:
    assert found(text) == []


def test_a_finding_is_a_phrase_with_its_place() -> None:
    [finding] = wording.check("Shareholders may find Apple attractive.")
    assert (finding.kind, finding.offset, finding.text, finding.value) == (
        Kind.PHRASE,
        28,
        "attractive",
        "advice",
    )


@pytest.mark.parametrize(
    "text",
    [
        "Apple holds a safe status.",  # "hold" isn't a rule: it's how the data is described
        "A buyback is not in the data.",  # whole words only
        "Someone wrote this.",  # "one" inside a word
        "Pricey is not a word the post uses, nor is sentimental.",
    ],
)
def test_parts_of_words_dont_count(text: str) -> None:
    assert found(text) == []


def test_the_writer_is_told_what_to_do_once_per_rule() -> None:
    findings = wording.check(
        "Investors: both have been attractive for a decade, and your price matters."
    )
    assert wording.instructions(findings) == [
        rule.instead for rule in wording.RULES
    ]  # every rule broken, each once, in RULES order


# From the 120 writings of 2026-10-14 (docs/benchmarks/2026-10-14-prose-checks/).
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "bringing a mix of technology and utility exposure to the calendar",
            [("exposure", "advice")],
        ),
        (
            "its liquidity position warrants a closer look despite its growing dividend",
            [("warrants a closer look", "advice")],
        ),
        ("tight liquidity warrants attention", [("warrants attention", "advice")]),
        (
            "Iberdrola's tight liquidity warrants closer attention",
            [("warrants closer attention", "advice")],
        ),
        ("Readers should note that Iberdrola reports", [("Readers", "audience")]),
        ("a dynamic to monitor given its liquidity warnings", [("monitor", "advice")]),
        ("Apple's dividend has grown steadily for over a decade", [("decade", "duration")]),
    ],
)
def test_what_the_retries_wrote_instead(text: str, expected: list[tuple[str, str]]) -> None:
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # "warrants" describing the data, not steering the reader.
        "though its liquidity position warrants a watch status",
        # A claim the list is complete, not a count: true in all 13 writings that made it.
        "Apple and Iberdrola are the only companies going ex-dividend this week.",
        "Meanwhile, the broader market faces a heavy earnings slate.",
        "Apple is considered safe due to a long streak of consecutive raises.",
    ],
)
def test_what_the_rules_leave_alone(text: str) -> None:
    assert found(text) == []


def test_findings_come_in_the_order_they_are_written() -> None:
    # The count comes first in the text, the advice rule first in RULES.
    assert found("Both look attractive.") == [("Both", "count"), ("attractive", "advice")]


# The 27B's X post (2026-10-28, docs/benchmarks/2026-10-28-x-posts/nike/): held
# for "buy", which is part of a company's name.
BEST_BUY = "In Consumer Cyclical, $NKE leads by yield at 4.37%. Best Buy is next."


def test_a_companys_name_is_not_advice() -> None:
    assert found(BEST_BUY) == [("Buy", "advice")]
    assert wording.check(BEST_BUY, names=["Nike, Inc.", "Best Buy Co., Inc."]) == []


def test_a_name_is_masked_where_it_is_written_and_nowhere_else() -> None:
    text = "Best Buy is next. Analysts say buy."
    [finding] = wording.check(text, names=["Best Buy Co., Inc."])
    # The offset is the word's own: masking keeps every position.
    assert (finding.text, finding.offset) == ("buy", text.index("buy."))


def test_a_short_name_isnt_masked_inside_other_words() -> None:
    # "Pay" (a two-letter prefix would be "Pa") is too short to try, and whole
    # words only: masking "Sell" must not reach "Selling".
    assert found("Selling pressure.") == [("Selling", "advice")]
    assert wording.check("Selling pressure.", names=["Sell Co"]) == [
        wording.check("Selling pressure.")[0]
    ]


def test_allow_lets_a_text_use_a_word_a_rule_names() -> None:
    text = "The share price is 77.8% below its high, and its valuation…"
    assert [(f.text, f.value) for f in wording.check(text, allow={"price"})] == [
        ("valuation", "market")
    ]
