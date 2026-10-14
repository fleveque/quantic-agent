import pytest

from quantic_agent import weekahead
from quantic_agent.corrections import compare, word_diff
from quantic_agent.store import Correction

# quantic#492, run 3's Catalan, as written and as merged after review.
WRITTEN = (
    "Apple, en comparació, manté una classificació de seguretat sòlida amb un creixement "
    "recent que ha quedat lleugerament per davant de la seva tendència de llarg termini."
)
MERGED = (
    "Apple, en comparació, manté una sòlida classificació de segura amb un creixement "
    "recent que ha quedat lleugerament per darrere de la seva tendència de llarg termini."
)
SUMMARY = "Apple encapçala la setmana amb un pagament trimestral."


def post(
    locale: str = "ca", summary: str = SUMMARY, watch: str = WRITTEN, yield_: str = "0.0032"
) -> str:
    """A file in a post's shape: frontmatter, then the locale's headings."""
    headings = weekahead.LOCALES[locale].headings
    return (
        f'---\nkind: "week_ahead"\nlocale: "{locale}"\ndata:\n  dividend_yield: {yield_}\n---\n\n'
        f"## {headings['summary']}\n\n{summary}\n\n## {headings['watch']}\n\n{watch}\n"
    )


def test_a_post_merged_as_written_has_no_corrections() -> None:
    assert compare("ca", post(), post()) == []


def test_each_changed_section_is_one_correction() -> None:
    assert compare("ca", post(), post(watch=MERGED)) == [Correction("ca", "watch", WRITTEN, MERGED)]


def test_whitespace_that_reading_back_ignores_isnt_a_correction() -> None:
    assert compare("ca", post(), post(watch=f"{WRITTEN}\n\n")) == []


def test_a_file_left_out_is_a_correction_of_the_whole_file() -> None:
    assert compare("it", post("it"), None) == [Correction("it", "file", post("it"), None)]


def test_a_file_that_isnt_a_post_any_more_is_kept_whole() -> None:
    broken = post().replace("---\n\n##", "\n##")
    assert compare("ca", post(), broken) == [Correction("ca", "file", post(), broken)]


def test_the_data_and_the_frontmatter_are_compared_as_yaml() -> None:
    edited = post(yield_="0.0033").replace('kind: "week_ahead"', 'kind: "weekly"')
    found = compare("ca", post(), edited)
    assert [(c.section, c.drafted, c.published) for c in found] == [
        ("data", "dividend_yield: 0.0032\n", "dividend_yield: 0.0033\n"),
        ("frontmatter", "kind: week_ahead\nlocale: ca\n", "kind: weekly\nlocale: ca\n"),
    ]


def test_the_word_diff_marks_what_the_reviewer_changed() -> None:
    assert word_diff(WRITTEN, MERGED) == (
        "Apple, en comparació, manté una {+sòlida+} classificació de "
        "[-seguretat sòlida-]{+segura+} amb un creixement recent que ha quedat lleugerament "
        "per [-davant-]{+darrere+} de la seva tendència de llarg termini."
    )


@pytest.mark.parametrize(
    ("before", "after", "marked"),
    [
        ("same text", "same text", "same text"),
        ("", "new", "{+new+}"),
        ("old", "", "[-old-]"),
        # Several words changed together are one mark, not one per word.
        ("a b c d", "a x y d", "a [-b c-]{+x y+} d"),
        ("  indented", "  indented", "  indented"),
        # A sentence added after the last word doesn't change that word.
        ("the end.", "the end. And more.", "the end. {+And more.+}"),
    ],
)
def test_word_diff(before: str, after: str, marked: str) -> None:
    assert word_diff(before, after) == marked
