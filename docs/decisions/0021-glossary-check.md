# 0021 — A glossary per locale, checked like wording

**Status:** accepted · **Date:** 2026-11-03

## Context

The translation check (decision 0013) holds a translation with figures or a length far from the
English's. It can't see a wrong word, and the reviewer kept correcting the same kind: Catalan
"divisió" for dividend and Portuguese "lucros" (profits) for results (quantic#492), Italian
"esclusioni dividendi" and German "ohne Dividende" for ex-dividend (quantic#511), and on
quantic#539 Italian "passa in esistenza dividendo", "rendita" and German "ex dividende". Since
milestone 14 `--sync` stores each correction (decision 0016), and nothing read them back: the
next week could make every one again.

CLAUDE.md "Next" item 6 offered two options: a per-locale glossary with a check that holds a
known-wrong term, the only one that guarantees anything, and past corrections retrieved as
examples for the translator. On 2026-11-03, after reviewing quantic#539, the author chose the
glossary, as milestone 17.

## Decision

**Each locale in `locales.json` has a glossary**: entries of what was written wrong (`wrong`, one
or more forms), what to write instead (`right`), and the pull request where the reviewer
corrected it (`seen`). [`glossary.py`](../../src/quantic_agent/glossary.py) matches the wrong
forms as whole words, any case, any spacing between words. `match_case` is for a wrong form
that's a right one in another case: German "dividende" is wrong, "Dividende" right.

**Every entry comes from a correction the reviewer made.** The 13 seed entries are each a
sentence the agent wrote and the reviewer changed, stored by `--sync`, and the tests hold each
drafted sentence and pass its published one. Terms raised only in a review the reviewer didn't
act on (Spanish "atención sanitaria", French "marques", Portuguese "marcas" on quantic#539) are
left out. The English has no glossary.

**The translator is told the right terms**, at the end of its prompt. A translation that still has
a wrong one is sent back with each named and the right one, up to the writer's three attempts. On
the last it's checked as it is: a wrong term is a problem, and a problem holds the locale (exit 6).
Figures and length aren't sent back; they hold at once, as before.

**An English wording rule for what an ex-dividend date is** (`ex_dividend`: "payout", "payment" or
"dividend period"), after "marking the start of their payout periods" on quantic#539 went into all
seven locales. It's checked in the writer's loop, before anything is translated.

## Consequences

- Measured on run 10's English ([benchmarks](../benchmarks/2026-11-03-glossary/README.md)): without
  the glossary 9 of 30 translations had a listed wrong term, 6 of 10 in Catalan; with it, none
  published one and none was held. Telling the translator didn't lower the first attempt's rate;
  the retry did, each in one. A retried translation costs a call, seconds.
- No false positives in the 14 published post files. The three hits there are real mistakes the
  reviewer left in W45.
- It's a list, like the wording rules (decision 0017): an unlisted mistake passes, and a listed
  form is wrong in every sense. "Coupe" catches "coupe-vent" too: a hyphen ends a word.
- Adding an entry is editing `locales.json` and adding its drafted and published sentences to
  `tests/test_glossary.py`; a test fails for an entry with no sentence. Proposing entries from
  `--sync`'s corrections automatically isn't built: which words in a corrected sentence were the
  term is a judgement.
- Past corrections as the translator's examples is still open.
