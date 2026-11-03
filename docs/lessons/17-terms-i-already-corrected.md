# Lesson 17 — Terms I already corrected

**Milestone 17** — each locale has a glossary of terms I corrected in review, and a translation
that uses one is sent back. Milestone 14 stored my corrections and nothing read them, so the
Italian of quantic#539 could write "passa in esistenza dividendo", a phrase that means nothing,
the week after I'd fixed "esclusioni dividendi" for the same idea. Now a term I've corrected
doesn't get published again. Measuring it taught me that telling the model wasn't what worked.

*Also readable as a [formatted page](https://claude.ai/artifact/MspjfkztwMMkK8kW9FdsWj), with a [code walkthrough](https://claude.ai/artifact/Gv6Mqt1BoXdnze2ybtDgTV) of every
change the milestone made.*

---

## A glossary is data, again

Lesson 15's wording rules were a tuple in Python. These are per locale, so they live in
`locales.json` next to each language's headings:

```json
{
  "wrong": ["esistenza dividendo"],
  "right": "stacca il dividendo",
  "seen": "quantic#539"
}
```

`glossary.terms` turns each entry into a frozen dataclass, `Term`, and `Term.pattern` builds the
regex: the wrong forms joined with `|`, each word escaped with `re.escape`, `\s+` between words,
`\b` at both ends, case-insensitive. So "esistenza\n  dividendo" over a line break still matches.
In Go I'd have unmarshalled into a struct and compiled a `*regexp.Regexp` per entry; in Elixir,
`Jason.decode!` and `Regex.compile!/2`. In all three the table is data and the code doesn't
change when it does.

`seen` matters more than it looks. Every entry names the pull request where I changed it, and the
tests hold each drafted sentence and pass the sentence I published instead, verbatim from what
`--sync` stored. `test_every_entry_comes_from_a_correction` fails for an entry with no sentence:
a word banned on a guess. Terms from Claude's review of quantic#539 that I didn't actually change
("atención sanitaria", "marques") aren't in it.

## German nouns broke case-insensitive

My German correction was "ex dividende" to "ex Dividende". German capitalises nouns, so lowercase
"dividende" is always wrong and "Dividende" always right. A case-insensitive pattern can't tell
them apart; it would hold the fix. So a `Term` has `match_case`, false by default, true for that
one entry. Python's `re` takes flags as an int you OR together; with `match_case` it's `0`, without
it `re.IGNORECASE`. Breaking it on purpose (always `re.IGNORECASE`) failed two tests: the German
sentence I published, and the test written for the case.

## A test that proved nothing

I wrote "Le découpage reste." to show that "coupe" inside a word isn't matched. Then I removed the
`\b`s to watch it fail, and every test passed. "Découpage" doesn't contain "coupe": it's
"découpa-ge". The test was checking a word that couldn't match either way. "La découpe reste."
does contain it, and with that sentence, removing the boundaries fails the test. A test I hadn't
broken was a test I hadn't checked.

## Sent back, like a figure

`translate` used to be one call. Now it's the writer's loop: at most three attempts, and a
translation with a wrong term gets a message naming it and the right one:

```
That translation has terms it can't use: 'esistenza dividendo' should be 'stacca il dividendo'.
Translate both fields again.
```

`dict.fromkeys` keeps each term once, in order. It's Python's ordered set, as in lesson 14. Still
there after the third attempt, the term goes into the translation's problems, and a problem holds
that locale as before. Figures and length aren't sent back: they held at once before this
milestone and still do, so nothing about how often a locale is held changed except for the new
check.

## A field named like a module

My first `Locale` had a field called `glossary`, typed `tuple[glossary.Term, ...]`, in a file that
imports the module `glossary`. Pyright was happy and every test passed. Then, writing the
walkthrough, I went to explain why that annotation means the module, and checked instead:

```
>>> typing.get_type_hints(weekahead.Locale)
AttributeError: 'tuple' object has no attribute 'Term'
```

Since Python 3.14, annotations are evaluated lazily, when something asks for them, and in the
class's namespace. There, `glossary` is the field's default, `()`, so `glossary.Term` is
`().Term`. Dataclasses only ask for a forward reference, so nothing failed until something asked
for real types. The field is `terms` now, and a test asks for the types. In Go a struct field can
share a package's name safely: field names live in their own scope, and types resolve at compile
time. Here the type checker and the tests both missed it, and explaining the code found it.

## What measuring showed

I translated run 10's English as the agent drafted it, 10 times each into Italian, German and
Catalan with the 27B, without the glossary and then with it:

| | without | with |
|---|---|---|
| Catalan with a listed term | 6 of 10 | 0 |
| German | 1 of 10 | 0 |
| Italian | 2 of 10 | 0 |
| held | 0 | 0 |

But the "with" runs also record how many attempts each took, and Catalan needed a second attempt
6 times out of 10. That's exactly how often it got it wrong with no glossary at all. The right
terms are in its prompt, and the first attempt ignored them just as often. What fixed it was the
check sending the translation back, and every retry fixed it the first time. That's lesson 15's
point again from the other side: an instruction in the prompt isn't a guarantee, a check in code
is.

The Italian "in esistenza dividendo" never came back in 20 translations. It was one bad sample,
and it's in the list because it was published once.

## What it can't see

The retried Italian wrote "passa in stacco del dividendo", which is awkward and isn't in the
list. A German retry left out the verb. A glossary catches the mistakes I've already made, and
nothing else. I still read every locale.

And the English said "marking the start of their payout periods", which is wrong about what an
ex-dividend date is, and all seven translations said it too. That's not a translation problem, so
it's a wording rule for the English (`ex_dividend`), checked before anything is translated.

## What I'm taking on

- A correction stored and never read is a note to self. Make the next run read it.
- Put the evidence next to the rule: each entry names its pull request, and a test holds its
  sentence.
- Case-insensitive is a choice per language. German nouns made it a flag.
- Break every test once. One of mine was checking a word that couldn't match.
- Don't name a field after a module its annotation uses: since 3.14 the annotation is read lazily,
  in the class, where the field's default wins.
- Measure the instruction and the check separately. Here the instruction did nothing and the check
  did everything.

---

**Previous:** [Lesson 16 — A shortlist every morning](16-a-shortlist-every-morning.md)
