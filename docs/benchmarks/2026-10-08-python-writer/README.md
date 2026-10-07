# The writing phase in Python, measured — 2026-10-08

Milestone 8 of the Python version: research, then a separate writer given only the question, today's
date and the data, with the same prompts as the Go version's
[as built](../2026-10-07-writer/README.md), and the validator with Go's later fixes (numbers in words,
"16 and 17", list lengths, the question and today's date as sources) plus a weekday check. Real runs
of `quantic-agent --research`, `qwen3.5:9b`, live data from quantic.finance, on the target machine.
The same three questions as Go's, three runs each, all within about a minute.

| Question | Traced (exit 0) |
|---|---|
| Which companies go ex-dividend in the next 10 days? | 0/3 |
| Is Microsoft going ex-dividend this month? | 3/3 |
| Which stocks go ex-dividend in the next six months? | 1/3 |
| **All** | **4/9** |

[Every run, as printed](m8-python.txt). Tokens per run, both phases: 1,872–3,301.

## What the flagged answers did

- **A wrong count.** "two companies go ex-dividend within the next 10 days", then four listed.
- **Right counts, not traceable.** "four companies" (correct: four of the six fall in the window) and
  "two other companies". No list in the data has four or two items: a count of a filtered subset is
  derived, as Go's measurement found.
- **Reasoning in the answer.** One answer argued with itself for a paragraph ("Wait, calculating: Oct
  8 + 9 days = Oct 17"), despite `think: false`, and concluded that all six companies fall in the
  window. Its derived "Oct 18", "9" and "2" were caught. It also read "Oct 8-10" and "Oct 16-17" as a
  date plus the numbers -10 and -17: false positives, fixed in this milestone by reading a range of
  days as two dates. The stored run re-checked afterwards with `--run 3` (end of the file) reports 6
  figures instead of 8.
- **A derived date.** "Adding six months to today brings the date forward to approximately
  2027-04-08."
- **A wrong statement, caught by chance.** "there are no stocks listed in the dataset that go
  ex-dividend within the next six months", then nine listed. It was flagged only for its "180 days".

## What passed

All three Microsoft answers ("Yes, ... today, 2026-10-08"), and one six-months answer that listed all
nine stocks. In Go's run of the same three questions the day before, 7/9 traced; the calendar was a
day older, and nine runs can't separate two versions with the same prompts.

## Stopping and resuming

[Two real runs stopped with Ctrl-C and resumed](stop-and-resume.txt). GPU use went from 91% to 0%
within two seconds. A run stopped during research resumed without calling the tool again; one stopped
while writing resumed with no MCP server reachable. The first resumed run ended `answered` with an
answer that is wrong: "no companies ... within the next 10 days", when Microsoft went ex-dividend
that day. Every figure in it traces. The provenance check verifies figures, not claims.
