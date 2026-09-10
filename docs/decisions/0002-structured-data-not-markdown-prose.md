# 0002 — Posts are structured data plus prose, not markdown documents

**Status:** accepted · **Date:** 2026-09-10 · **Extends:** [0001](0001-agentic-research-constrained-writing.md)

## Context

The original plan had the agent emit a markdown file per post, opened as a PR. Two problems surfaced
once the actual output was described concretely.

**Presentation.** The Dividend Week Ahead is mostly data — an ex-dividend table with per-row safety
badges, coloured yields, ticker chips linking to `/stocks/:symbol`. Markdown renders that as a grey
generic table. The components that would make it look like Quantic already exist in the app, and
markdown has no way to reach them. Letting the agent emit HTML or HEEx instead is worse: unreviewable
in a diff, an injection surface, and it welds content to the frontend of the day it was written.

**Validation.** Numbers embedded in prose have to be validated by extracting numeric tokens with a
regex and matching them heuristically — with known false positives on years, list positions and
version numbers, and a genuinely hard locale-formatting problem once translation is in scope
(`3,400.50` vs `3.400,50`).

## Decision

A post is YAML frontmatter carrying **typed data** plus a markdown body carrying **only prose**. The
layout is a Phoenix template per post kind, which the agent does not control.

Rendering is NimblePublisher at build time with MDEx (raw HTML disabled) for the prose. A malformed
post fails the build, not a request. Merging to `main` already deploys, so PR merge → deploy → live.

**Prose contains no figures at all.** Every number lives in a typed frontmatter field.

## Consequences

**Provenance validation becomes exact.** `data.ex_dividends[0].amount` either equals what
`dividend_calendar` returned for that symbol or it doesn't. Field comparison replaces regex
extraction — no normalisation guesswork, no false positives. The body is validated by the much
simpler assertion that it contains no unaccounted numerics at all.

**Locale number formatting stops being the agent's problem.** Numbers never appear in translated
text; the `data` block is byte-identical across all seven locale files and Phoenix formats figures at
render time with the app's existing localisation. The translation validator drops its locale-aware
numeric normalisation entirely and asserts the data block is unchanged — a stronger guarantee than
the one it replaces.

**Presentation decouples from generation.** A redesign of `/insights` touches templates only. Old
posts pick it up for free; nothing is regenerated.

**Charts are free.** `data.charts` names an existing SVG chart component and a symbol. Server-side,
theme-aware, no image generation, no stale PNGs.

**Cost: a new post shape needs a new template.** Four planned formats, so this is cheap. If format
count ever grew large, revisit.

**Cost: the agent's writing prompt is harder.** "Write an interesting paragraph containing no
numbers" is a real constraint, and small models will violate it. The validator catches it, but expect
retries — and expect this to be where the accept-rate metric first bites.

**Rejected — directives in the body** (`{{ block: ex_dividends }}`). Needs a custom parser, is an
injection surface fed by model output, and lets the agent make layout decisions it has no basis for.
