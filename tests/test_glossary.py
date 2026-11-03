import pytest

from quantic_agent import glossary, weekahead
from quantic_agent.glossary import Term

# Each entry's evidence: a sentence as the agent translated it and as the
# reviewer published it, verbatim from the corrections --sync stored
# (quantic#492 is run 3, quantic#511 run 7, quantic#539 run 10).
CORRECTED = [
    (
        "es",
        "En ganancias, se espera que GE Vernova reporte resultados el mismo día",
        "En resultados, GE Vernova presenta sus cifras el día después",
    ),
    (
        "ca",
        "un estat de seguretat que reflecteix el creixement de la seva divisió.",
        "un estat de seguretat que reflecteix el creixement del seu dividend.",
    ),
    (
        "ca",
        "L'agenda d'accions sense dividendes d'aquesta setmana abarca sectors com financeres",
        "El calendari de dates ex-dividend d'aquesta setmana abasta els sectors financer",
    ),
    (
        "fr",
        "Pax Global a subi une forte coupe de sa distribution",
        "Pax Global a fortement réduit sa distribution",
    ),
    ("de", "da es ex dividende geht.", "und diese Woche ex Dividende geht."),
    (
        "de",
        "Außerdem wird Pfizer Inc. diese Woche seine Gewinne melden",
        "Außerdem legt Pfizer Inc. diese Woche Quartalszahlen vor",
    ),
    (
        "de",
        "einen bedeutenden Datenpunkt im Bereich der Gesundheitsversorgung",
        "einen bedeutenden Datenpunkt aus dem Gesundheitssektor",
    ),
    (
        "de",
        "Der Kalender für die nächste Woche ohne Dividende umfasst Werte",
        "Der Ex-Dividenden-Kalender dieser Woche umfasst Werte",
    ),
    (
        "it",
        "passa in esistenza dividendo questa settimana",
        "stacca il dividendo questa settimana",
    ),
    (
        "it",
        "Il calendario degli esclusioni dividendi di questa settimana",
        "Il calendario degli stacchi dei dividendi di questa settimana",
    ),
    (
        "it",
        "con una lieve riduzione della sua rendita",
        "con una lieve riduzione dell'importo",
    ),
    (
        "it",
        "registra un moderato aumento della distribuzione in uscita",
        "registra un moderato aumento della cedola",
    ),
    (
        "pt",
        "enquanto também relata lucros na mesma semana",
        "enquanto também divulga seus resultados na mesma semana",
    ),
]


def wrong(text: str, locale: str) -> list[str]:
    return [h.text for h in glossary.check(text, weekahead.LOCALES[locale].glossary)]


@pytest.mark.parametrize(("locale", "drafted", "published"), CORRECTED)
def test_what_the_reviewer_corrected_is_held_and_what_they_wrote_passes(
    locale: str, drafted: str, published: str
) -> None:
    assert wrong(drafted, locale) != []
    assert wrong(published, locale) == []


def test_every_entry_comes_from_a_correction() -> None:
    # An entry with no sentence above is a word banned on no evidence.
    for code, locale in weekahead.LOCALES.items():
        for term in locale.glossary:
            assert term.seen.startswith("quantic#")
            assert any(
                glossary.check(drafted, [term]) for c, drafted, _ in CORRECTED if c == code
            ), term


def test_match_case_tells_a_wrong_form_from_a_right_one() -> None:
    assert wrong("Kinder Morgan geht ex dividende.", "de") == ["dividende"]
    assert wrong("Kinder Morgan geht ex Dividende.", "de") == []
    # Sentence case doesn't hide the rest.
    assert wrong("Lucros e resultados.", "pt") == ["Lucros"]


def test_whole_words_any_spacing() -> None:
    assert wrong("passa in esistenza\n  dividendo", "it") == ["esistenza\n  dividendo"]
    assert wrong("Le coupe-vent n'a rien à voir.", "fr") == ["coupe"]  # a hyphen ends a word
    assert wrong("La découpe reste.", "fr") == []  # "coupe" inside a word


def test_hits_come_in_the_order_they_are_written() -> None:
    text = "una rendita e poi esclusione dividendi, e ancora una rendita"
    assert wrong(text, "it") == ["rendita", "esclusione dividendi", "rendita"]


def test_the_translator_is_told_the_right_terms() -> None:
    told = glossary.told(weekahead.LOCALES["it"].glossary)
    assert told.startswith("Use these terms:\n")
    assert '- "stacca il dividendo", never "esistenza dividendo"' in told
    assert glossary.told(()) == ""


def test_the_translator_is_sent_each_wrong_term_once() -> None:
    hits = glossary.check(
        "rendita, rendita, distribuzione in uscita", weekahead.LOCALES["it"].glossary
    )
    assert glossary.again(hits) == (
        "That translation has terms it can't use: 'rendita' should be 'importo'; "
        "'distribuzione in uscita' should be 'cedola'. Translate both fields again."
    )


def test_an_entry_reads_as_locales_json_has_it() -> None:
    [term] = glossary.terms(
        [{"wrong": ["dividende"], "right": "Dividende", "seen": "quantic#539", "match_case": True}]
    )
    assert term == Term(("dividende",), "Dividende", "quantic#539", match_case=True)
    assert weekahead.LOCALES["en"].glossary == ()
