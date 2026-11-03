"""Terms a translation must not use, per locale (milestone 17).

The translation check (weekahead.check_translation) sees figures and a
length far from the English's. It can't see a wrong word. The reviewer can,
and kept correcting the same kind: Italian "passa in esistenza dividendo"
(quantic#539) for going ex-dividend, German "ex dividende", Portuguese
"lucros" (profits) for results (quantic#492). Milestone 14 stores each
correction; nothing read them back, so the next week could make them again.

So each locale in locales.json has a glossary: what was written wrong, and
what to write instead. The translator is told the right terms, and a
translation that still has a wrong one is sent back with it named, then
held if it's still there after the last attempt. A wrong term in the list is
never published.

Like wording.py, this finds phrases, not meanings. A mistake nobody has
listed passes, and a listed phrase is wrong in every sense it has: an entry
should come from a correction, and from reading where else the phrase could
be right.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Term:
    """What a translation mustn't write (wrong, any of them) and what it
    should (right). seen is where the reviewer corrected it. match_case is
    for a wrong form that is a right one in another case: German "dividende"
    is wrong, "Dividende" right."""

    wrong: tuple[str, ...]
    right: str
    seen: str
    match_case: bool = False

    @property
    def pattern(self) -> re.Pattern[str]:
        """Any wrong form as whole words, any spacing between them."""
        forms = (r"\s+".join(map(re.escape, form.split())) for form in self.wrong)
        flags = 0 if self.match_case else re.IGNORECASE
        return re.compile(rf"\b(?:{'|'.join(forms)})\b", flags)


@dataclass(frozen=True)
class Hit:
    """A wrong term found: as written, where, and the entry it broke."""

    text: str
    offset: int
    term: Term


def terms(entries: Iterable[dict[str, Any]]) -> tuple[Term, ...]:
    """A locale's glossary as locales.json has it."""
    return tuple(
        Term(
            wrong=tuple(entry["wrong"]),
            right=entry["right"],
            seen=entry["seen"],
            match_case=entry.get("match_case", False),
        )
        for entry in entries
    )


def check(text: str, glossary: Sequence[Term]) -> list[Hit]:
    """Every wrong term in text, in the order they appear."""
    found = [
        Hit(m.group(), m.start(), term) for term in glossary for m in term.pattern.finditer(text)
    ]
    return sorted(found, key=lambda h: h.offset)


def told(glossary: Sequence[Term]) -> str:
    """The glossary as the translator's prompt has it: empty with none."""
    if not glossary:
        return ""
    lines = [f'- "{t.right}", never ' + " or ".join(f'"{w}"' for w in t.wrong) for t in glossary]
    return "Use these terms:\n" + "\n".join(lines)


def again(hits: Sequence[Hit]) -> str:
    """The translator's next message: each wrong term once, with the right one."""
    broken = list(dict.fromkeys(h.term for h in hits))
    named = "; ".join(
        " or ".join(dict.fromkeys(repr(h.text) for h in hits if h.term == t))
        + f" should be {t.right!r}"
        for t in broken
    )
    return f"That translation has terms it can't use: {named}. Translate both fields again."
