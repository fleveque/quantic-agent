"""What the reviewer changed before merging a post (milestone 14).

A merge says the post was approved, not that it was approved as written: on
quantic#492 the reviewer corrected six of the seven locales on the branch
first. The agent reads each file back from the merge commit and compares it
with the one it wrote, section by section, the way the post is read: the
prose sections by their key, the data block as data, the rest of the
frontmatter together. Only what differs is kept.

This is capture only. Nothing here changes how the next post is written:
using the corrections (a glossary, retrieved examples) is later work, and
it needs them stored first.
"""

import difflib
import re
from typing import Any

import yaml

from quantic_agent import weekahead
from quantic_agent.store import Correction


def compare(locale: str, drafted: str, published: str | None) -> list[Correction]:
    """The sections of a locale's file that the reviewer changed. published
    is the file as merged, or None if it was left out. A file that doesn't
    read back as a post is one correction of the whole file. A change that
    reading back doesn't see (whitespace around a section) isn't one."""
    if published is None:
        return [Correction(locale, "file", drafted, None)]
    if published == drafted:
        return []
    try:
        draft_front, draft_sections = weekahead.read_back(drafted, locale)
        front, sections = weekahead.read_back(published, locale)
    except ValueError, yaml.YAMLError:
        return [Correction(locale, "file", drafted, published)]
    found: list[Correction] = []
    for key in dict.fromkeys([*draft_sections, *sections]):  # both files' keys, in order
        before, after = draft_sections.get(key, ""), sections.get(key, "")
        if before != after:
            found.append(Correction(locale, key, before, after))
    if draft_front.get("data") != front.get("data"):
        found.append(
            Correction(locale, "data", _yaml(draft_front.get("data")), _yaml(front.get("data")))
        )
    rest = {k: v for k, v in front.items() if k != "data"}
    draft_rest = {k: v for k, v in draft_front.items() if k != "data"}
    if draft_rest != rest:
        found.append(Correction(locale, "frontmatter", _yaml(draft_rest), _yaml(rest)))
    return found


def _yaml(value: Any) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)


def word_diff(before: str, after: str) -> str:
    """after, with what changed from before marked as git's --word-diff
    marks it: [-removed-]{+added+}. Each word carries the whitespace after
    it, so one change of several words is one mark, not one per word; the
    words are compared without it, so a word that only gained a space after
    it hasn't changed."""
    old, new = _words(before), _words(after)
    out: list[str] = []
    matcher = difflib.SequenceMatcher(
        None, [w.rstrip() for w in old], [w.rstrip() for w in new], autojunk=False
    )
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        removed, added = "".join(old[i1:i2]), "".join(new[j1:j2])
        if op == "equal":
            out.append(added)
            continue
        # The space after the change stays outside the marks.
        space = (added or removed)[len((added or removed).rstrip()) :]
        if removed.strip():
            out.append(f"[-{removed.rstrip()}-]")
        if added.strip():
            out.append(f"{{+{added.rstrip()}+}}")
        out.append(space)
    return "".join(out)


def _words(text: str) -> list[str]:
    """text as words, each with the whitespace after it, so that joining the
    list gives text back."""
    head = text[: len(text) - len(text.lstrip())]
    return ([head] if head else []) + re.findall(r"\S+\s*", text)
