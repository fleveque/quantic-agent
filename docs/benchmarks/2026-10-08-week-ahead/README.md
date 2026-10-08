# The Week Ahead, measured — 2026-10-08

Milestone 11: `quantic-agent --week-ahead` researches next week's ex-dividend dates with the agentic
loop, builds the post's data from the tool results, has the model write the English prose with no
figures in it, and translates it into six locales. On the target machine (RTX 4070 Ti Super 16GB,
Ollama 0.34.4), `qwen3.5:9b`, live quantic.finance data. The week after Thursday 2026-10-08 had two
companies going ex-dividend: Procter & Gamble and Coca-Cola.

## Research: the model must know what today is

[`runs.txt`](runs.txt), section 1: the first question named the week ("Monday 2026-10-12 to Sunday
2026-10-18") but not today. The calendar counts its days from today, and three runs of five asked
for 7 days, which from a Thursday ends before the week does. One noticed and asked again; two
didn't, and `weekahead.gather` refused them ("no dividend_calendar call covers the week"). One of
those then looked up this week's companies instead. With today's date in the question (sections 2
and 3), 20 runs of 20 gathered the whole week. The first calendar asked for was 10 to 120 days long,
except once: 7 days, followed at once by 30.

## Prose with no figures

The rule from the [format contract](../../rendering.md): a post's prose has no figures, not even in
words. [`prose.txt`](prose.txt), 20 writings per prompt from the same data:

| Prompt | Published within 3 attempts | First attempt clean | Figures written, all attempts |
|---|---|---|---|
| first | 18/20 | 0/20 | two ×39, five ×15, three ×7, twelve ×2, thirty ×1 |
| + don't count the companies | 20/20 | 1/20 | two ×27, five ×13, three ×5, twelve ×2 |
| + neutral field names | 19/20 | 5/20 | two ×22 |

"Five", "twelve" and "three" came from the data's field names: shown `cagr_5y` and `growth_ttm`, the
model wrote "five-year" and "trailing twelve months". Shown `long_term_growth` and `recent_growth`,
it didn't once in 60 attempts. "Two", the number of companies, persists even when the prompt names
it as forbidden: the retry, which names the figure, is what removes it. The last prompt is the one
merged.

End to end ([`runs.txt`](runs.txt)): with the first prompt, 7 of 10 runs published (3 still said
"two" after three attempts); with the merged one, 10 of 10, the prose taking 2 attempts in 4 runs
and 3 in 6. A run took 23–31 seconds, model loaded.

## Translations

114 translations from 19 published runs, 228 sections: none held. Every section was 0.95 to 1.37
times the length of its English; by locale, medians from 1.13 (`pt`) to 1.22 (`fr`, `de`). An
earlier probe of 24 sections gave 1.06 to 1.48. The band is 0.75 to 1.75.

The checks pass translations that are wrong. [`post/`](post/) is one real run's seven files. Its
Spanish is fluent but literal ("una bandera de precaución", "un cojín más seguro"). Its Catalan has
errors a reader sees at once: a word cut short ("Aquesta set destaquen"), Spanish words
("incrementos", "augmentos"), a misspelling ("similarmet"). An earlier probe turned "a pair of
consumer staples names go ex-dividend late in the week" into "Dues empreses ... al cap de
setmana": "two companies", a figure in a word the check only knows in English, and "at the
weekend", which is wrong.

## What the English says

Read against the data, most statements were right: Procter & Gamble's recent growth (0.0397) does
trail its five-year rate (0.0597), and Coca-Cola's (0.0422 against 0.0446) is close to its own. Some
weren't, with every check passing: one run gave Coca-Cola "recent acceleration", another said "the
safety posture for these firms remains strong" with Procter & Gamble on watch. Some leaned towards
advice: "offering a stable alternative in the same sector", "one must note". Provenance proves the
post has no invented figure; it can't prove the post is right, which is what review is for.
