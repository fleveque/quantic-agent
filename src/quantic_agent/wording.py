"""Wording a post's prose must not use (milestone 15).

The figure check (provenance.no_figures) proves the prose has no figures. It
can't see a sentence that leans towards advice, which design N5 forbids
("informational, never advisory"), or a count of the companies in words
the figure check doesn't read ("both", "a pair"). The writer's prompt
forbids both, and the model still wrote them: "offering distinct profiles
for income-focused investors" and "may influence sentiment" (2026-10-14,
the 27B), "a stable alternative" and "both sustained" (2026-10-08, the 9B).

So the English prose is checked for them, phrase by phrase, and a phrase
found is a Finding like a figure: sent back to the writer, named, with what
to do instead, and holding the post if it's still there after the last
attempt. Each rule is a pattern and that instruction.

This finds phrases, not meanings. It can't see a false claim ("a recent
acceleration" for a slowing dividend), and a new way of leaning towards
advice passes until a rule names it. What it does guarantee: a phrase a
rule names is never published.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from quantic_agent.provenance import Finding, Kind


@dataclass(frozen=True)
class Rule:
    """A kind of wording the prose mustn't use: name is stored with each
    finding; instead is what the writer is told."""

    name: str
    pattern: re.Pattern[str]
    instead: str


def _words(*alternatives: str) -> re.Pattern[str]:
    """Any of the alternatives as whole words, case-insensitively."""
    return re.compile(rf"\b(?:{'|'.join(alternatives)})\b", re.IGNORECASE)


RULES = (
    Rule(
        "audience",
        _words(
            r"investors?",
            r"readers?",
            r"income[- ](?:focused|oriented|seekers?)",
            r"you",
            r"your",
        ),
        "Don't address the reader or name an audience: describe the companies.",
    ),
    Rule(
        "advice",
        _words(
            r"buy(?:ing)?",
            r"sell(?:ing)?",
            r"recommend\w*",
            r"attractive",
            r"opportunit(?:y|ies)",
            r"alternatives?",
            r"consider(?:ing)?",
            r"worth",
            r"bargain",
            r"undervalued",
            r"overvalued",
            # Portfolio talk: "a mix of technology and utility exposure", 10
            # times in 120 writings.
            r"exposure",
            # Telling the reader where to look: "warrants a closer look", "a
            # dynamic to monitor". "Warrants a watch status" describes the data
            # and stays.
            r"warrants? (?:closer |extra )?(?:attention|a closer look)",
            r"(?:a )?closer (?:look|attention)",
            r"monitor\w*",
        ),
        "Don't judge whether anything is worth owning, don't suggest an action, and don't "
        "tell the reader what to look at.",
    ),
    Rule(
        "market",
        _words(r"sentiment", r"prices?", r"valuations?", r"upside", r"downside", r"volatil\w*"),
        "Don't speak of prices, valuations or market mood: the data has none of them.",
    ),
    Rule(
        "count",
        _words(r"both", r"pair", r"duo", r"trio", r"one", r"single", r"lone", r"sole"),
        'Don\'t count the companies, in any form: name them, or say "these companies".',
    ),
    Rule(
        # Figures in words the figure check doesn't read: "for over a decade".
        "duration",
        _words(r"decades?", r"centur(?:y|ies)", r"dozens?"),
        'No durations or amounts in words either: write "a long record", not "a decade".',
    ),
)


def check(text: str, *, names: Sequence[str] = (), allow: Collection[str] = ()) -> list[Finding]:
    """Every phrase in text that a rule names, in the order they appear.

    names are the companies the text is about: a rule's word inside one is
    the company's name, not advice ("Best Buy", 2026-10-28). allow is words a
    rule names that this text may use, in lower case: an X post about a
    company's yield needs "price", which the Week Ahead's prose doesn't."""
    masked = _masked(text, names)
    found = [
        Finding(text=m.group(), offset=m.start(), kind=Kind.PHRASE, value=rule.name)
        for rule in RULES
        for m in rule.pattern.finditer(masked)
        if m.group().lower() not in allow
    ]
    return sorted(found, key=lambda f: f.offset)


def _masked(text: str, names: Sequence[str]) -> str:
    """text with each company's name blanked out, keeping every offset. A
    name is written shorter than Quantic stores it ("Best Buy" for "Best Buy
    Co., Inc."), so each one's leading words are tried, longest first, down
    to its first word."""
    for name in names:
        words = re.findall(r"[\w'\u2019&-]+", name)
        for n in range(len(words), 0, -1):
            short = " ".join(words[:n])
            if len(short) < 3:
                break
            pattern = re.compile(rf"\b{re.escape(short)}\b", re.IGNORECASE)
            if pattern.search(text):
                text = pattern.sub(lambda m: " " * len(m.group()), text)
                break
    return text


def instructions(findings: list[Finding]) -> list[str]:
    """What the writer is told to do instead, once per rule broken, in the
    order of RULES."""
    broken = {f.value for f in findings}
    return [rule.instead for rule in RULES if rule.name in broken]
