# Lesson 11 — Seven files, one set of figures

**Milestone 11** — the Dividend Week Ahead, end to end: research, a data block built by code, prose
by the model with no figures in it, six translations, each checked, and seven files in a folder. The
first milestone that produces the thing the agent exists for. It's also where the model's limits
stopped being hypothetical: it didn't know what day it was, it counted when told not to, and its
Catalan passed every check while being visibly wrong.

*Also readable as a [formatted page](https://claude.ai/artifact/VFJgaAxgiZx8YiwPFuFBgL), with a [code walkthrough](https://claude.ai/artifact/M1FoS3w2xAD3AehxYu7G2u) of every change the
milestone made.*

---

## What the post can say

The content plan's Week Ahead has amounts, yields, declared raises, cuts and radar movers. Quantic's
public tools don't have most of that: the calendar gives a name, a sector, an ex-dividend date and a
frequency, and `get_stock` a safety status, a streak and growth rates, but not the coming dividend's
amount. The radar is a user's own watchlist, and the agent never reads user data. I chose to build on
what's there and list what's missing, so Quantic can add it later as its own work. I also chose to
keep the agentic loop for research rather than have code make the calls: the model decides what to
look up, and code checks that it looked up enough.

## Which week

"The week ahead" is the Monday after today:

```python
def week_after(today: date) -> Week:
    return Week(today + timedelta(days=7 - today.weekday()))
```

`weekday()` is 0 for Monday, so from a Thursday (3) that's four days on, and from a Sunday (6), one.
The post is named by its ISO week, `start.isocalendar()`, which gives a year, a week and a day. The
year is the ISO year, not the calendar one: the week that starts on Monday 2024-12-30 is 2025-W01, and
2026 has a week 53. Go has `time.Time.ISOWeek()` returning the same pair; Elixir's
`Date.beginning_of_week/1` and `:calendar.iso_week_number/1` split it in two. The test has both edges.

## The model didn't know what day it was

The first question named the week, "Monday 2026-10-12 to Sunday 2026-10-18", and three runs of five
asked the calendar for this:

```
tool dividend_calendar {"days": 7} → 544 bytes
```

The calendar counts its days from today. Seven days from Thursday stop before the week's Sunday. One
run noticed and asked again; two didn't, and one of those then looked up this week's companies. The
model can't count forward from a date it was never told. With "Today is Thursday 2026-10-08." at the
start of the question, twenty runs of twenty gathered the whole week.

What caught it was the code that builds the data, not the model:

```
research didn't gather the whole week: no dividend_calendar call covers the week 2026-10-12 to 2026-10-18
```

`gather` takes the latest calendar that covers the week and needs a `get_stock` for every company in
it. Anything less fails the run in its research phase, to be resumed. A post that quietly left a
company out would be wrong about the week, with every figure in it traced.

## Data by code, prose by the model

The model never touches a figure. Code turns the recorded tool results into the data block, checks it
against those same results with `provenance.check_data`, and only then asks for prose. A check on
data that code built from the tools looks as if it can't fail. It can when the code is wrong: making
`gather` round a growth rate turns the run into

```
data no tool returned: ex_dividends[0].growth_ttm = 0.0397
```

The prose comes back as JSON. Pydantic writes the schema, Ollama enforces it:

```python
class Prose(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str
    watch: str


PROSE_FORMAT = Prose.model_json_schema()
```

`chat(..., format=PROSE_FORMAT)` makes Ollama constrain the generation to the schema token by token,
and `Prose.model_validate_json` reads the reply back. The same model class is the schema the model is
held to and the parser of what it says, as the tools' argument models were in lesson 05.

## Prose with no figures, measured

The format contract says prose has no figures, not even "three names". Design open question 8 asked
whether a small model could manage that. Twenty writings per prompt, from the same data, with up to
three attempts, the figures named back to the model each time:

```
current       published 18/20  attempts {2: 6, 3: 14}         figures {'two': 39, 'five': 15, 'three': 7, ...}
counts        published 20/20  attempts {1: 1, 2: 10, 3: 9}   figures {'two': 27, 'five': 13, 'three': 5, ...}
counts+names  published 19/20  attempts {1: 5, 2: 9, 3: 6}    figures {'two': 22}
```

"Five" and "twelve" came from the data's field names. Shown `cagr_5y` and `growth_ttm`, the model
wrote "five-year" and "trailing twelve months". Shown `long_term_growth` and `recent_growth`, it never
did, in sixty attempts. The file keeps the tools' names, and only the writer sees the plain ones. "Two"
is the number of companies, and no prompt stopped it, not even one that forbids "two" by name. The
retry is what removes it. With the last prompt, ten real runs of ten published, taking two or three
attempts each.

## YAML: what a string looks like

YAML guesses types from how a value looks, and PyYAML quotes the strings it would itself misread:

```
symbol: 'ON'
ex_dividend_date: '2026-10-16'
growth_ttm: 0.039728682170542484
```

Unquoted, `ON` is a boolean to a YAML 1.1 parser, and `2026-10-16` a date. PyYAML leaves `1E3` bare
because its own rules need a dot in a float, but a YAML 1.2 parser reads it as a thousand. Quantic
doesn't depend on a YAML parser yet, so which one will read these files is still open. So every
string value is double-quoted, with a representer for a `str` subclass:

```python
class _Quoted(str):
    """A string to write double-quoted in YAML, whatever it looks like."""


_Dumper.add_representer(_Quoted, _represent_quoted)
```

Keys stay plain `str`, so they stay bare. In Go, yaml.v3 picks the style per node and you'd set
`Style: yaml.DoubleQuotedStyle` on each one. Ruby's Psych would quote `'ON'` too and leave `1E3` alone.
Each file is then read back with `yaml.safe_load` and must say exactly what was checked. That also
catches prose that writes its own `## ` heading, which would otherwise become a section of its own.

## Package data

The prompts are long enough to read better as text files, and the section headings in seven languages
are a table. Both ship inside the package:

```python
resources.files("quantic_agent").joinpath("prompts", "week_ahead.md").read_text(encoding="utf-8")
```

`importlib.resources` finds the file wherever the package is installed, from a checkout, a wheel or a
zip, which `Path(__file__).parent` only does on disk. Go embeds files at compile time with
`//go:embed`. Elixir keeps them in `priv/` and finds them with `Application.app_dir/2`. The translation
prompt is a `string.Template` (`$language`), since a prompt with JSON in it would fight `str.format`'s
braces. I built a wheel and loaded it from a fresh environment to be sure the files go with it.

## Seven locales, checked by shape

Each translation is checked for figures and for a length between 0.75 and 1.75 times the English.
Across 114 real translations, every section came in between 0.95 and 1.37, and none was held. Then I
read them. The Spanish was literal but fine. The Catalan had a word cut short ("Aquesta set
destaquen"), Spanish words ("incrementos") and a misspelling ("similarmet"). An earlier probe turned "a
pair of" into "Dues empreses", which is "two companies": a figure, in a word the check only knows in
English. The checks are structural, and they pass a translation nobody should publish. The design
publishes five locales on those checks alone, and whether that can stand is now an open question for
me, not something the agent decides.

The English can be wrong too, with no figure in it: one run gave Coca-Cola "recent acceleration" for a
dividend growing more slowly than its average. Provenance proves no figure was invented, and review
has to do the rest.

## What I'm taking into milestone 12

- Tell the model what day it is. It can't count from a date it was never given.
- Code builds what can be built; the model writes only what can't. Check both anyway.
- A JSON Schema from Pydantic, enforced by Ollama, is the cheapest way to get structure back.
- Field names leak into prose. What the model is shown is part of the prompt.
- YAML types depend on the parser: quote what must stay a string, and read the file back.
- `importlib.resources` for package data, and a built wheel to prove it ships.
- A structural check passes fluent nonsense. The reviewer reads what the checks can't.

---

**Previous:** [Lesson 10 — A memory for the house voice](10-a-memory-for-the-house-voice.md)
