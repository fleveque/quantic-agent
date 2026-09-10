# Content format and rendering

How a generated post becomes a page that looks like Quantic. The contract between what the agent
emits and what the Phoenix app renders.

---

## The problem with "the agent writes markdown"

Markdown can express prose. It cannot express the Quantic design system.

The Dividend Week Ahead is mostly *data*: a table of ex-dividend dates with per-row safety badges,
yield figures that want colour, ticker chips that link to `/stocks/:symbol`, raise percentages in
green and cuts in red. In markdown that's `| MSFT | 2026-09-18 | 0.83 |` — a grey generic table. The
components that would make it look like Quantic already exist in the app and markdown has no way to
reach them.

Emitting HTML from the agent is worse: unreviewable in a PR diff, an injection surface, and it welds
generated content to whatever the frontend looked like the day it was generated.

## The format: structured data + named prose

A post is **one file per locale** with YAML frontmatter and a markdown body:

- **Frontmatter carries the data** — typed fields, not markdown tables.
- **The body carries only prose** — the paragraphs a human would actually write.
- **The layout is a Phoenix template per post kind**, not something the agent controls.

```yaml
---
kind: week_ahead
period: 2026-W38
published_at: 2026-09-13
locale: en
fold_after: summary          # registration gate splits here
manifest_id: 01JQ8F...       # provenance link

data:
  summary:
    ex_dividend_count: 23
    raises_count: 3
    cuts_count: 1
    at_risk_count: 2
  ex_dividends:
    - symbol: MSFT
      ex_date: 2026-09-18
      amount: 0.83
      currency: USD
      yield_pct: 0.71
      safety: strong
    - symbol: O
      ex_date: 2026-09-19
      amount: 0.2695
      currency: USD
      yield_pct: 5.42
      safety: watch
  raises:
    - symbol: ITW
      previous: 1.50
      current: 1.55
      change_pct: 3.33
      currency: USD
  charts:
    - component: dividend_growth
      symbol: ITW
---

## What to watch

Three consumer-staples names go ex-dividend in the same week for the first time this
quarter, and the REIT cohort keeps its recent pattern of monthly payers holding steady
while quarterly payers drift.
```

The body has no numbers in it. That is a **rule**, not a coincidence — see below.

## Rendering

**Build-time compilation with [NimblePublisher](https://github.com/dashbit/nimble_publisher).** It
reads the markdown files at compile time, parses frontmatter, and produces structs — zero runtime
parsing cost, and a malformed post fails the *build* rather than a request. Since merging to `main`
already deploys to production, the flow is clean: PR merged → deploy → post live.

**Markdown engine: [MDEx](https://github.com/leandrocp/mdex)** (comrak via NIF) with raw HTML
disabled. Faster than Earmark, GFM tables and footnotes, and — since the input is model-generated —
the fact that unsafe HTML is off by default matters.

**Layout: a Phoenix template per `kind`.** `week_ahead.html.heex` knows the shape of a Week Ahead:
where the summary tiles go, that `data.ex_dividends` renders through `<.dividend_table>`, that each
row gets a `<.safety_badge>` and a `<.ticker_chip>`, that `data.charts` renders the existing SVG
chart components. The prose slots in by heading.

```
post.md ──build──► %Post{data: %{...}, prose: %{...}}
                          │
                          ▼
              week_ahead.html.heex
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  <.stat_tiles>   <.dividend_table>    <.chart> (existing SVG components)
                    └ <.safety_badge> <.ticker_chip>
```

**The agent never controls presentation.** It supplies typed data and paragraphs. A redesign of
`/insights` touches templates only — no regenerating content, no rewriting old posts.

### Why not directives in the body?

An alternative is `{{ block: ex_dividends }}` markers in the markdown that a parser swaps for
components. Rejected: it needs a custom parser, it's an injection surface fed by model output, and it
lets the agent make layout decisions it has no basis for making. A fixed template per kind is
simpler, safer, and smaller to validate.

The cost is that a new post *shape* needs a new template. That's fine — there are four planned
formats, not four hundred.

### Charts

`data.charts` names existing components by symbol. The SVG chart components already shipped on
`/stocks/:symbol` render server-side, stay theme-aware, and cost the agent nothing to "generate" —
it just names one. No image generation, no stale PNGs.

---

## Two problems this format removes

### 1. Provenance validation gets exact

When numbers live in prose, validating them means extracting numeric tokens with a regex and matching
them heuristically against tool output. When numbers live in typed frontmatter fields, validation is
**field-by-field comparison against the manifest** — `data.ex_dividends[0].amount` either equals what
`dividend_calendar` returned for MSFT or it doesn't. No regex, no normalisation guesswork, no false
positives on years and list positions.

This makes the prose rule enforceable and cheap: **prose must contain no figures at all.** The
validator asserts zero unaccounted numerics in the body, and every figure is checked structurally.
A model that writes "yields rose about 40 basis points" in the body fails validation and gets sent
back.

### 2. Locale number formatting disappears

The [translation design](design.md#35-translation) worried about `3,400.50` vs `3.400,50` — the
validator having to normalise per locale before comparing numeric multisets. That problem is gone.

Numbers never appear in translated text. They live in the data block, identical across all seven
locale files, and **Phoenix formats them at render time** using the app's existing localisation. The
translation pass only ever touches prose.

So the translation validator simplifies to: same structure, same prose sections, no numbers
introduced, length within tolerance. The `data` block is asserted byte-identical to the source, which
is a much stronger guarantee than the one it replaces.

---

## What this needs from the Quantic repo

Prerequisite work, none of it agent work:

1. `/insights` route, index, and per-locale routing consistent with the language subdomains.
2. NimblePublisher + MDEx wired up, one `Post` struct per kind.
3. `week_ahead.html.heex` and the components it composes (most already exist).
4. The free-registration gate honouring `fold_after`, with `schema.org` flexible-sampling markup.
5. Sitemap and hreflang entries for the section.
