# 0017 — Wording rules for the prose, sent back like figures

**Status:** accepted · **Date:** 2026-10-14

## Context

The figure check (decision 0013) proves the Week Ahead's prose has no figures. It can't see wording.
The writer's prompt forbids advice and counting the companies, and the model still did both. On
2026-10-14 the 27B wrote "offering distinct profiles for income-focused investors" and "may
influence sentiment" (run 4). The 9B had written "a stable alternative" and "both sustained". Design
N5, informational and never advisory, was guaranteed only by the reviewer. Measured on 60 writings
of the same week's prose ([benchmarks](../benchmarks/2026-10-14-prose-checks/README.md)): 22 had
such wording, 9 of them addressed to "investors", one as plain advice ("investors should note the
tight liquidity warning").

The author chose this as the next milestone, after the options in CLAUDE.md "Next".

## Decision

**A list of wording rules, checked on the English prose, each a pattern and an instruction**
([`wording.py`](../../src/quantic_agent/wording.py)): audience ("investors", "readers", "you"),
advice ("buy", "attractive", "exposure", "warrants a closer look", "monitor…"), market ("sentiment",
"price", "valuation"), count ("both", "one", "pair"), duration ("decade", "dozen"). Whole words,
any case.

**A match is a `Finding`, of kind `phrase`, like a figure.** The writer gets it back, named, with
each broken rule's instruction, up to the same three attempts. Still there after the last attempt,
it holds the post (exit 4, nothing written). It's stored with the draft, and `--run N` re-checks it.
The store needed no migration: a finding's `value` names the rule.

**English only.** Translations are checked for figures and length as before. A rule written in
English can't read Catalan. A translation of clean English adding advice hasn't been seen, but
it isn't checked.

**The rules come from what the model wrote.** Each was added after reading its matches in context
across the 120 writings, and some were left out on that evidence. "The only companies" (13 times)
claims the list is complete and was true each time. "The broader market" was narrative. "Warrants"
alone describes the data ("warrants a watch status"), so only "warrants attention" and "warrants a
closer look" are rules.

## Consequences

- With the check, 60 of 60 writings published: 33 at the first attempt, 23 at the second, 4 at
  the third. A writing takes 13 s on average instead of 9 s. That's seconds in a run of a few
  minutes.
- It finds phrases, not meanings, and it's a list. The model's retries found new wordings ("for
  those monitoring", "readers should note"), and each round of measurement found a few more. A
  phrase a rule names is never published. Anything else still needs the reviewer.
- False claims pass: "Each name carries a safe profile" with Iberdrola on watch. Checking a claim
  against the data is a different check (CLAUDE.md "Next").
- "Both X and Y", correct English, is sent back. The prompt forbids "both" in any use, and a retry
  costs seconds.
- A rule in the list is a word the post can't use, in any sense. Adding one should start from real
  writings, and from reading its matches.
