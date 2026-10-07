# Lesson 06 — Every figure has a source

**Milestone 6** — the provenance validator. Design N1 says the agent never invents a number, and
until now that was a sentence in a prompt. Now it's checked: every number and date in an answer has
to be one a tool returned, exactly, or the run says so and exits 4. The Go version was mostly regular
expressions and a recursive walk over decoded JSON, and both port almost line for line. What doesn't
port is what Python's JSON values *are*: one of them made `true` count as the number 1.

*Also readable as a [formatted page](https://claude.ai/artifact/P2UTWg28qBgcLkCVXDYbDP), with a [code walkthrough](https://claude.ai/artifact/3oJ654NbHc8nioJo7JHVkr) of every change the
milestone made.*

---

## What landed

```
$ uv run quantic-agent --research "List the ex-dividend dates coming up over the next two months."
tool dividend_calendar {"days": 60} → 1232 bytes (315ms)
Based on the data, here are the upcoming ex-dividend dates for the next two months (from October
7 to December 6, 2026):
...
quantic-agent: 1 figure(s) in the answer came from no tool result:
  'December 6, 2026' (date 2026-12-06)
$ echo $?
4
```

The tool returned the calendar from October 7 and a window of 60 days. December 6 is the end of that
window, and the model worked it out itself: correct arithmetic, and exactly what N1 forbids, because a
figure the model derived is one nothing checked. A derived figure has to come from a calculator tool,
where it enters the record like any other result.

`quantic_agent/provenance.py` has three checks, for two kinds of output:

- **`check_data`** for a post's typed data block (docs/rendering.md): every number and every string
  must be one a tool returned. That's a lookup per field, which is why posts keep figures in typed
  fields.
- **`check_prose`** for free text, such as a research answer: it finds the figures in the text
  (numbers, dates, years) and reports the ones no tool returned.
- **`no_figures`** for a post's prose, which may contain none at all.

## The manifest, and what JSON values are in Python

Everything is checked against a `Manifest`: an index of every number, date and string in a run's
successful tool results, each with where it came from (`dividend_calendar#0 $.stocks[1].ex_dividend_date`).
Building it is a walk over whatever `json.loads` returned, and that's where Python and Go part.

Go decoded every JSON number as a `float64`. Python gives an `int` for `10` and a `float` for `0.83`.
That turns out to be harmless, even helpful: dictionary keys are compared by value, and `10 == 10.0`
with the same hash, so "10.0 days" in prose finds the integer 10 a tool returned. A test says so.

Booleans are the problem. In Python `bool` is a subclass of `int`:

```python
print("True == 1:", True == 1, "| isinstance(True, int):", isinstance(True, int))
```

```
True == 1: True | isinstance(True, int): True
```

So a manifest that indexed `"done": true` as a number would account for a "1" in the prose, and
`"partial": false` for a "0". The walk matches booleans first and skips them:

```python
match value:
    # bool first: True is an int in Python (True == 1, and they hash
    # alike), so "done": true would otherwise account for a "1".
    case bool() | None:
        pass  # booleans and nulls carry no figures
    case int() | float():
        self._numbers.setdefault(value, []).append(at)
```

With the `bool()` case removed, the test written for it fails, and on more than I expected:

```
E       AssertionError: assert [] == ['1', '0']
```

Both "1 company" and "0 cuts" were vouched for by booleans. Go never had this: its decoder keeps
`bool` and `float64` apart, and a Go `switch` on type matches exactly.

## A type for JSON, defined in terms of itself

Strict pyright wanted to know what `case list():` held. A value typed `object` narrows to `list[Unknown]`,
which strict mode rejects. Python 3.12's `type` statement can define a type that refers to itself:

```python
type JSON = bool | int | float | str | list[JSON] | dict[str, JSON] | None
```

With the value typed `JSON`, `case list():` narrows it to `list[JSON]` and `case dict():` to
`dict[str, JSON]`, so the recursive walk type-checks with no casts. Go's `any` with a type switch did
the same job without the type checker asking.

## Finding figures in prose

The prose check is the Go version's regular expressions, translated. Python's `re` can name its
groups, which removes Go's index arithmetic (`atoi(s, loc, 4)`):

```python
_MONTH_DAY = re.compile(
    rf"\b(?P<month>{_MONTHS})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<year>\d{{4}})\b)?",
    re.IGNORECASE,
)
```

`m["month"]` and `m["day"]` read the parts. The `rf` prefix makes a raw f-string, so `\b` stays a
regex word boundary while `{_MONTHS}` is substituted. Literal braces in the pattern, such as
`\d{1,2}`, then have to be doubled.

Dates are found first and blanked out with spaces of the same length, so the "8" in "Oct 8" isn't
read again as a number, and every offset still points into the original text. Then numbers, with the
same rules for what isn't a claim: digits inside words (`Q3`, `qwen3.5`, `COVID-19`) and list
positions at the start of a line. A bare four-digit number from 1900 to 2100 is a year, accounted for
by any returned date in that year.

Matching is exact. "0.27" for an amount of 0.2695 is reported: it's a different claim, even if it's a
fair rounding. Rounding belongs to the template that displays a figure, never to the text that states
it.

## The empty string is in every string

Two tests failed the first time, and both for the same reason, in a check I'd written to see whether
a number is part of a word:

```python
before = s[start - 1] if start > 0 else ""
...
return before.isalnum() or before in "._" or ...
```

At the very start of the text, `before` is `""`, and:

```python
print("" in "._")
```

```
True
```

The empty string is a substring of every string, so every number at the start of a text counted as
part of a word and was skipped. "180 days ahead" passed with its invented 180. Go compared a single
character, which can't be empty. The fix stands a space in for the text's edges. That one was found
by tests that already existed, not by breaking anything on purpose, which is the other half of why
they're worth writing first.

## Structured data, and dictionaries that keep their order

`check_data` takes a post's data block in whatever form it comes, a Pydantic model, a dataclass, a
dict, and needs plain JSON values to walk. Go encoded to JSON and decoded again. Pydantic does it in
one call that accepts anything it can serialise:

```python
_AS_JSON: TypeAdapter[Any] = TypeAdapter(Any)
_AS_JSON.dump_python(data, mode="json")
```

Then the same walk, reporting every number *and every string* no tool returned, so an invented ticker
fails like a rounded yield: one test's data gets `ex_dividends[0].symbol = MSFTX`, another's
`ex_dividends[0].yield_pct = 0.7`.

Go randomises map iteration on purpose, so its `CheckData` sorted the keys to report findings in the
same order every run. Python dictionaries have kept insertion order since 3.7, so the findings come
in the data's own order, the order a person reads the post in, with no sort.

## Six real answers

I asked three questions twice each, with qwen3.5:9b and live data from quantic.finance. Four answers
traced fully. The other two:

- **"October 16 and 17"**: "16" is read with the month, but the bare "17" is a number, and no tool
  returned the number 17. The date the model meant *was* in the data. A real limit of the parser, and
  Go met the same one; its fix ("16 and 17" read as two dates) belongs to milestone 8 in this port,
  with its other findings.
- **"from October 7 to December 6, 2026"**: a date the model computed. Exactly what the check is for.

Go's six runs at the same milestone traced five; its sixth said "the next 4 months", also derived. The
numbers say less than the cases do: what gets through is figures in words, which aren't parsed yet,
and what gets caught is arithmetic the model shouldn't be doing.

## What changed from the Go version

- **Booleans are skipped explicitly**, because Python's are integers.
- **Integers and floats** are one key per value, where Go had only `float64`.
- **A recursive `JSON` type alias** for the walk, where Go used `any`.
- **Named groups** in the regular expressions.
- **Pydantic serialises the data block**, where Go round-tripped through JSON.
- **Findings come in insertion order**, where Go sorted map keys.
- **Offsets count characters**, where Go's counted bytes: `"€1"` starts at 0 and its digit is at 1, not 3.

## What I'm taking into milestone 7

- Know what a library's values are, not just their names: Python's JSON booleans are integers.
- Order `match` cases from the most specific class to the most general, as with `except`.
- `"" in s` is always true. Guard the edges with a real character, not an empty one.
- Exact matching is the point: a figure is either one a tool returned or a claim nobody checked.
- A run's answer and its tool calls now need to outlive the process. Milestone 7 puts them in SQLite.

---

**Previous:** [Lesson 05 — The first real tool](05-the-first-real-tool.md)
