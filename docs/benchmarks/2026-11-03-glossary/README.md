# The glossary, measured — 2026-11-03

Milestone 17 ([decision 0021](../../decisions/0021-glossary-check.md)). Run 10's drafted English
(quantic#539, as the agent wrote it, before the reviewer's corrections) translated into Italian,
German and Catalan, 10 times each, by the default model (Qwen3.8-27B `UD-IQ3_S`, `num_ctx` 32768),
first with every glossary emptied (**baseline**), then with the glossary (**glossary**). Every
reply was checked against the full glossary either way. The script reads the source from the
agent's database and calls `weekahead.translate`; each translation is in
[`runs.jsonl`](runs.jsonl), with its attempts, seconds, the wrong terms its final text still had,
its problems and its text.

| Locale | Baseline: wrong term published | Glossary: needed a retry | Glossary: wrong term published | Held | Seconds, baseline → glossary |
|---|---|---|---|---|---|
| ca | 6 of 10 ("sense dividend", 11 times) | 6 of 10 | 0 | 0 | 6.4 → 10.2 |
| de | 1 of 10 ("dividende", twice) | 2 of 10 | 0 | 0 | 5.8 → 7.0 |
| it | 2 of 10 ("rendita", twice) | 3 of 10 | 0 | 0 | 5.8 → 7.1 |

## What it shows

- **Telling the translator did nothing measurable.** With the right terms in its prompt, the first
  attempt still had a wrong one about as often as with none: Catalan 6 of 10 both ways. The
  guarantee comes from the check sending it back, and every retry fixed it in one.
- **Nothing was held.** No translation needed a third attempt.
- **The cost is seconds**: one more call for the translations that need it, 4 s on average in
  Catalan, about 1 s in German and Italian.
- **"In esistenza dividendo" didn't recur** in 20 Italian translations, with or without the
  glossary. quantic#539's Italian was one sample; the term is in the list because it was
  published once, not because it's frequent.

## What it doesn't show

- **New mistakes nobody listed pass**, as designed. Retried Italian wrote "passa in stacco del
  dividendo" (run 8), German "wird in dieser Woche Ex-Dividende" with no verb (run 7). The
  reviewer still reads every locale.
- **The source still said "marking the start of their payout periods"**, and every translation
  carried it. The new English wording rule (`ex_dividend`) stops it upstream, before translation;
  this benchmark translated the drafted English on purpose, to reproduce the week's mistakes.
- **False positives** were measured separately: the glossary over the 14 published post files in
  Quantic's `priv/insights/` (W44, W45) found 3 terms, all real, all in W45 locales the reviewer
  left uncorrected (Catalan "sense dividend" twice, German "ex dividende" in the summary).
