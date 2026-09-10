# Content plan

What the agent publishes, how often, and where it lands. Companion to the [design](design.md) and the
[format & rendering contract](rendering.md).

---

## Principles

- **Recurring and time-anchored beats evergreen volume.** A reader who knows something lands every
  Sunday comes back. A pile of undated listicles doesn't.
- **Weekly, not daily.** Two reasons. Google's scaled-content-abuse policy explicitly targets bulk
  machine-generated pages, and quantic.finance is a real domain with real ranking pages already
  earning traffic — 365 auto-written pages a year is a way to damage it. Second, a 14B model at daily cadence
  produces daily *mediocre* output, and a review queue that's a chore is a review queue that stops
  being read. Cadence is easy to raise later; a penalised domain is not easy to fix.
- **Don't duplicate the ranking pages.** The aristocrats/kings/monthly/highest-yield/safest-REIT
  pages already own the "best X" queries. Content is dated and event-driven; those pages are
  evergreen and structural. Content *links to* them.
- **Informational, never advisory** (N5). Describe what the data says. Never "this is a buy".

---

## Formats

### 1. The Dividend Week Ahead — flagship, weekly (Sunday)

The one to build first and prove.

| | |
|---|---|
| **Trigger** | Weekly, Sunday |
| **Tools** | `dividend_calendar`, `get_dividends`, `get_radar`, dividend-safety data |
| **Length** | ~600 words + tables |
| **Delivery** | PR to `/insights` (7 locales) + social variants in the review queue |

Shape:

- *N companies go ex-dividend this week* — table: ticker, ex-date, amount, yield
- *Raises declared* — ticker, old → new, percentage change
- *Cuts and at-risk flags* — from the existing DividendSafety / REIT FFO work
- *Radar movers* — what crossed target prices
- *What to watch* — one short paragraph, the only freely written prose, and it contains **no figures**

Every number comes from a tool call. The "what to watch" paragraph is where the model earns its
keep, and it's deliberately the only place it's allowed to be interesting.

### 2. Raise & Cut Notes — event-driven

A dividend raise is news on the day it's declared, not the following Sunday. Short (~250 words), one
company, triggered by the data rather than the calendar. Feeds social directly and gives the weekly
digest something to link back to.

### 3. Valuation Deep Dives — evergreen, slow drip

Longer write-ups strengthening the `/stocks/:symbol` pages already shipped. This is where retrieval
over filings and news earns its place. Target ~2/week, and only after the weekly digest's accept rate
proves the pipeline. Not before.

### 4. Monthly Dividend Health Report — later

Aggregate: raises vs cuts this month, distribution of payout ratios, sector movement. Naturally
shareable, naturally linkable, and a good showcase for the screener data.

### Anti-formats

Price predictions. Buy/sell recommendations. "Top 10" listicles that cannibalise the ranking pages.
Anything daily. Anything whose value depends on the model having an opinion.

---

## Where it lives: `/insights`

A new markdown-backed section in the Phoenix app. The agent opens a PR adding one `.md` file per
locale per post; the app renders them.

Locale comes from the request host, which Quantic already does app-wide, so `/insights` needs no
locale-aware routing of its own and canonical/hreflang/sitemap come for free from the existing SEO
layer. **The section itself doesn't exist yet** — prerequisite work in the private Quantic repo, not
agent work, and it blocks the first content milestone.

### Registration gate

Full articles are gated behind **free registration** — the content doubles as a signup driver.

The trap to avoid: showing Googlebot the full article while showing readers a gate is **cloaking**,
and it would undermine the exact SEO bet this section exists to make. The supported pattern is
Google's *flexible sampling*:

- A genuine free portion — enough to be useful and to rank.
- The remainder gated behind free registration.
- `schema.org` markup declaring the split honestly: `isAccessibleForFree: false` plus a `hasPart`
  block marking the gated section. Googlebot then indexes the full text knowing it's gated, and no
  cloaking penalty applies.

**Agent-side consequence:** the agent must emit the fold itself, because it's the only thing that
knows where the natural hook sits. Each draft carries a `fold_after` field in its frontmatter naming
the block the gate opens after, and the writing prompt is instructed to place it where curiosity
peaks. See the [format contract](rendering.md).

For the Week Ahead that's typically: free portion gives the *counts and the shape* — "23 companies go
ex-dividend this week, three raises declared, one cut" — and the gate opens onto the full table with
tickers, dates and amounts. The free half creates the specific question the gated half answers.

Everything about the gate itself — auth, markup, rendering — is Quantic-repo work. The agent's only
obligation is the marker.

---

## Locales

All seven from the first content milestone. The multiplier is the point: one reviewed post becomes
seven indexable pages, and the hosts to carry them already exist:

| Locale | Host | | Locale | Host |
|---|---|---|---|---|
| `en` | `quantic.finance` *(canonical)* | | `pt` | `pt.quantic.finance` |
| `es` | `quantic.es` | | `de` | `de.quantic.finance` |
| `ca` | `quantic.cat` | | `fr` | `fr.quantic.finance` |
| | | | `it` | `it.quantic.finance` |

The review burden is handled by *not* human-reviewing every translation:

- **`en` is the source** — Quantic's reference language and the canonical host. This is the draft the
  provenance validator gates and the one you read in full.
- **`es` is spot-checked** — the locale you can actually judge, so it surfaces in the queue for a
  fluency read. Not a re-review of facts: the `data` block is byte-identical to the source, so no
  figure can differ.
- **`ca`, `fr`, `de`, `it`, `pt` publish on machine verification** — same data block, same structure,
  no numerics introduced, length in tolerance. A locale that fails is held; the rest publish.

Full mechanism in [design §3.5](design.md#35-translation).

Register follows existing Quantic conventions: informal throughout, Brazilian Portuguese for `pt`.
Note this is per-locale markdown, not gettext — the msgid rules don't apply to content.

---

## Social distribution

The agent drafts the long post and its social variants **in the same run, sharing one manifest**, so
one review approves both. Telegram (@quantic_es) and Reddit first; both are text-native and both
tolerate a link.

Nothing posts automatically (N2). The queue holds the text; a human presses publish.

---

## The metric

Human accept rate per format, tracked in the `reviews` table. It's the only honest measure of whether
the agent is producing anything worth reading. A format sitting below its threshold is a broken
format — fix the task, don't lower the bar.
