# Lesson 08 — A loop that can stop

**Milestone 8** — the research loop grows up, and the Python version reaches where the Go version
stopped. Migrations move to a library. The agent researches within a budget, then writes in a
separate step that can't call tools. It waits out Quantic's rate limit, and saves itself between the
two steps, so a run stopped halfway carries on later instead of starting over. The validator learns
what Go's did after its milestone 8, and two things more, both found in real runs. Along the way: a
library that commits behind your back unless asked not to, an SDK that hides a rate limit as a
mistake, and an answer that passed every check and was wrong.

*Also readable as a [formatted page](https://claude.ai/artifact/VqfYLE86knX1NP1Agt9XNP), with a [code walkthrough](https://claude.ai/artifact/R4AmcMHTenLcAeaQqAWeDY) of every change the
milestone made.*

---

## Migrations, by hand and with Alembic

In milestone 7 I wrote migrations myself, following Go. Go then moved to goose, the library most Go
projects use, to have done both. In Python the equivalent is **Alembic**, which runs on SQLAlchemy.
The closest thing to goose is yoyo-migrations: plain `.sql` files, tiny, but untyped, and its lock
is a row in a table that a crashed process leaves behind. I went with what Python projects use
([decision 0010](../decisions/0010-alembic-for-migrations.md)).

| | By hand (milestone 7) | Alembic (milestone 8) |
|---|---|---|
| Bookkeeping table | `schema_migrations`, mine | `alembic_version`, Alembic's |
| Files | `0001_*.sql`, plain SQL | `versions/0001_*.py`, with `upgrade()` and `downgrade()` |
| Order | the file names | each file names the one before it: `down_revision = "0001"` |
| Undo a migration | no | `downgrade` |
| Dependency | none | Alembic, SQLAlchemy, Mako, MarkupSafe |

A migration is a Python module with two module-level names and two functions:

```python
from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN tokens INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN tokens")
```

Alembic finds them through `script_location = "quantic_agent:migrations"`, a *package:directory*
pair that resolves wherever the package is installed. I checked it from a built wheel, not just from
my checkout.

### A library that commits behind your back, again

Milestone 7's lesson was that `sqlite3`'s default mode commits pending work inside `executescript`.
Alembic runs every migration in a transaction, so I expected that to be someone else's problem now.
Before relying on it, I wrote a migration that creates a table and then fails, and ran it:

```
== default
  error: OperationalError (sqlite3.OperationalError) near "this": syntax error
  tables: ['alembic_version', 't', 'u']
  version: [('0001',)]
== autocommit_false
  error: OperationalError (sqlite3.OperationalError) near "this": syntax error
  tables: ['alembic_version', 't']
  version: [('0001',)]
```

In the default mode, the failed migration's table `u` stayed, with the version still at `0001`: every
later open would fail on "table u already exists". SQLAlchemy *thinks* it began a transaction, but
`sqlite3` in its default mode only really begins one before an `INSERT` or `UPDATE`, never before a
`CREATE TABLE`. Opening the connection with `autocommit=False` (Python 3.12+) makes `sqlite3` keep a
real transaction open at all times, and the rollback is whole. The test does exactly that experiment;
without the setting:

```
E       AssertionError: assert 'half' not in ['alembic_version', 'drafts', 'half', 'runs', 'tool_calls']
```

### Every migration must be able to go back down

A `downgrade()` is code like any other, so a test takes the schema down to nothing and back up.
Deleting one `DROP TABLE` line:

```
E       AssertionError: assert ['alembic_version', 'drafts'] == ['alembic_version']
```

### The database that came before the library

A database created by milestone 7 records its history in `schema_migrations`, which Alembic doesn't
read: it would see nothing applied and run `0001` again. So opening the store hands it over once, in
one transaction. Alembic's `stamp` writes the version into `alembic_version` without running
anything, and the old table goes. I tested it on a database made by the merged milestone 7 code
itself, not only by the test's imitation of one.

### The lock, measured again

Alembic has no lock for SQLite, as goose hadn't. Go found goose without a lock collided *more* than
its hand-written code. Mine, four processes opening each new database, 20 rounds:

```
== Alembic, without the lock
47 of 80 opens failed
50 of 80 opens failed
== Alembic, with the lock
0 of 200 opens failed
0 of 200 opens failed
```

Ten times worse than milestone 7's 5 of 80, and each failing process died within half a second, far
inside the five-second busy timeout: SQLite refused rather than waited. My first guess was that
`autocommit=False` caused it. Measured without it, still without the lock: 50 and 47 of 80, as many,
but different errors, two processes applying the same migration:

```
26 × sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) table runs already exists
12 × sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) duplicate column name: phase
```

So the guess was wrong, and the lesson is Go's: a migration tool for SQLite assumes one migrator. The
`flock` from milestone 7 stays.

## Waiting out a rate limit

Anonymous callers get 60 requests a minute from Quantic. Its code sends `429` with
`{"error": "rate limited — try again shortly"}`, counts in fixed one-minute windows, and sends no
`Retry-After`. Go retried inside its own MCP client. Mine is the official SDK's, so the first
question was what the SDK does with a 429. I taught the fake server to send one:

```
quantic_agent.quantic.RPCError: Server returned an error response (-32603)
```

An `RPCError` is what the research loop hands back to the model as *its* mistake, to correct. Nothing
about the request was wrong. And a 429 on the `initialized` notification was dropped silently.

### Under the SDK

httpx2, the SDK's HTTP library, lets you replace its *transport*, the piece that actually sends a
request. So the retry sits underneath the SDK, where a 429 is still a 429:

```python
response = await self._inner.handle_async_request(request)
if response.status_code != 429 or request.method != "POST":
    return response
```

My first version raised `RateLimitedError` from the transport when the retries ran out. The SDK runs
each request in a task of its own, inside an anyio task group, and a task that raises makes the group
cancel everything else in it, including the call waiting for the reply:

```
CALL RAISED CancelledError CancelledError('Cancelled via cancel scope 7f3bc4465310')
EXIT RAISED ExceptionGroup ExceptionGroup('unhandled errors in a TaskGroup', [RateLimitedError(...)])
```

A `CancelledError` is what Ctrl-C looks like to the agent: the run would have been recorded as
interrupted, and the real error would only have surfaced when the session closed. So when the
retries are spent, the transport *answers* instead: a JSON-RPC error with a code of the agent's own,
`-32029`, from the range JSON-RPC leaves to implementations. The SDK passes it up like any server
error, and `quantic.py` turns that code into `RateLimitedError` (exit 3, resumable).

### Backoff with jitter, and a number too big to be a float

The waits double from one second to a cap of 30, each with "equal jitter": half the step, plus a
random part of the other half. Nine attempts wait between 60.5 and 121 seconds in all, and the test
checks the *shortest* schedule outlasts a minute, the mistake Go's version caught in itself.

Go needed `d <= 0` because shifting an `int64` too far overflows. Python's integers don't overflow,
but converting one to a float can:

```
>>> 1.0 * 2 ** 1100
OverflowError: int too large to convert to float
```

So the exponent is capped at 64, and a test asks for retry number 2000.

Waiting is `await asyncio.sleep(wait)`. Go needed a timer in a `select` with `ctx.Done()`; here, a
cancellation lands at the `await`, so Ctrl-C or the run's deadline ends the wait at once. The test
sets an hour's wait and a 0.2-second deadline.

## Running out is not failing

Milestone 5's loop raised `TooManyCallsError`. Design §3.2 says running out of budget is a normal end,
and writing goes ahead with what was gathered. So the budget is data:

```python
@dataclass(frozen=True)
class Budget:
    calls: int = 4
    tokens: int = 16_000
```

Go wrote `cmp.Or(r.Budget.Calls, DefaultBudget.Calls)` because a Go struct's zero value can't tell
"not set" from 0. A dataclass has defaults. `frozen=True` makes instances immutable, and
there's one more rule: ruff refuses `budget: Budget = Budget()` as a function default, because a
default is evaluated *once*, when the function is defined, and shared by every call. For a frozen
object that's harmless; ruff can't know, so the default is a module-level `DEFAULT_BUDGET`.

### What research gathered, and who owns it

Go's `Research` returned the value and the error together, so a failed run still knew its calls and
tokens. A Python function either returns or raises, so I turned it around: the caller creates the
`Research`, and the loop fills it in place.

```python
gathered = agent.Research(calls=run.calls, tokens=run.tokens, exhausted=run.exhausted)
await researcher.research(run.input, gathered, on_call=on_call)
```

If the tool server dies on the third call, `gathered` already holds the three calls and every token
spent. Go's lesson had a bug about this: `append` writing into the caller's array, sometimes,
depending on capacity. Python has no "sometimes":

```
recorded = [Call("dividend_calendar", {"days": 10}, "{}")]
gathered = Research(calls=recorded)
gathered.calls.append(Call("dividend_calendar", {"days": 20}, "{}"))
print(len(recorded), gathered.calls is recorded)
```

```
2 True
```

A list passed in is the same list, always. Here that's the design, said in the docstring: "gathered is
continued in place". In Elixir it couldn't be; in Ruby, it's `<<` on the same array, as here.

## Two phases

Research is the loop with tools. When the model stops asking, what it says is discarded. Writing is
one `chat` with **no tools**, given the standing instruction, today's date, the question, and each
successful call's result:

```
Today's date: 2026-10-08

Question: Which companies go ex-dividend in the next 10 days?

Data from dividend_calendar {"days": 10}:
{"from":"2026-10-07","days":10,"stocks":[{"name":"Microsoft", ...
```

"Today" is the day the run *started*, even when it's resumed a week later: the answer describes the
data fetched then. Go's writer, untold, once worked from "October 2023".

Look at the two dates, though. These runs started at 00:19 in Spain: the agent's local date was
October 8, Quantic's (UTC) still October 7, and the data says so. The writer was told the 8th, and
wrote "Microsoft goes ex-dividend today". In Spain, it did. Which date "today" should be is a
question for the design, not for me to settle in passing; it's recorded for the next milestone.

A run whose research gathered nothing, because the model answered from memory or every call was
refused, doesn't reach the writer at all. It ends `no_data` (exit 5): an answer about nothing isn't an
answer. That state needed migration `0003`, which rebuilds `runs`, because SQLite can't change a
`CHECK` constraint. Go had to switch foreign keys off for the rebuild, outside a transaction, which
needed goose's `NO TRANSACTION` mode. Alembic's connection is one the store never turns foreign keys
on for, so the rebuild runs in an ordinary transaction and ends with `PRAGMA foreign_key_check`.

## Checkpoints, and claiming a run

A run is saved when research ends: `runs.phase` goes from `research` to `write`. So
`quantic-agent --resume N` knows where to start. Stopped while writing, it calls no tool again.
Stopped during research, it replays the stored calls to the model as if just made, and carries on
within what's left of the budget.

Who gets the run if I resume it twice at once? One `UPDATE`:

```
UPDATE runs SET state = 'running', error = NULL, finished_at = NULL
 WHERE id = ? AND state IN ('interrupted', 'failed', 'no_data')
```

SQLite runs one write at a time. The first `UPDATE` changes the row, and the second finds it
`running` already and matches nothing: `rowcount` is 0. The test starts ten threads, each with its own
connection, on the same run. Exactly one wins. Without the condition:

```
E       assert (10, 0) == (1, 9)
```

Go's version had `AND phase != 'done'` too. I ported it, then broke it, and nothing failed: a run only
gets an answer by ending `answered` or `unverified`, and neither can be resumed. As with milestone
3's DNS guard, a check no test can fail is a check I can't show is needed, so it went.

## What the validator learned

Go's measurement after its milestone 8 found the validator blind to numbers in words ("ten stocks"
for nine) and to "October 16 and 17". Its fixes are ported: words from two to ninety-nine are
numbers ("one" is left out, usually a pronoun); a day pair is two dates; every list's length counts as
returned, so "nine stocks" checks against a nine-item calendar; and the question and the run's date
count as sources, so repeating "the next six months" invents nothing.

Two more, from this version's real runs. Milestone 7 left one: "Tuesday, October 9" passed, and
October 9 is a Friday. A weekday written with a date now has to be that date's:

```
'Tuesday, October 9' (date --10-09, but 2026-10-09 is a Friday)
```

A weekday alone ("on Friday") isn't checked: nothing says which Friday. And one answer this
milestone wrote "Oct 8-10", read as the date "Oct 8" and the number -10. A range of days is now two
dates. The run that showed it was stored, so `--run 3` re-checked it against the same data: 6 findings
instead of 8, the real ones left.

## Measured

The same three questions as Go's measurement, three runs each, live data
([all of them](../benchmarks/2026-10-08-python-writer/README.md)): **4 of 9 traced**. Go's version
traced 7 of 9 the day before. Same prompts, a day's different calendar, and nine runs can't separate
them. What the flagged ones did is more useful than the score: "two companies" followed by four; a
correct "four companies" that no list in the data accounts for, since it's a count of a filtered
subset; a date six months out the model computed itself; and one answer that argued with itself for a
paragraph ("Wait, calculating: Oct 8 + 9 days = Oct 17") despite `think: false`, and concluded wrong.

## The payoff

A real run, stopped with Ctrl-C while the model worked, then resumed:

```
$ quantic-agent --research "Which companies go ex-dividend in the next 10 days?"
tool dividend_calendar {"days": 10} → 810 bytes (314ms)
quantic-agent: run 1 interrupted
quantic-agent: to carry on from where it stopped: quantic-agent --resume 1
quantic-agent: stopped; the request in flight was cancelled
$ nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader   # before Ctrl-C, then 2s after
91 %
0 %
$ quantic-agent --resume 1
quantic-agent: resuming run 1 in its research phase, with 1 tool call(s) recorded
quantic-agent: run 1 answered
Based on the data provided, there are no companies listed that go ex-dividend within the next 10 days from today's date (2026-10-08). The earliest ex-dividend date in the dataset is 2026-10-08.
```

No tool line on resume: the recorded call was replayed, not made again. The GPU was free two seconds
after I stopped it. A second run, stopped while writing, resumed with the MCP address pointed at
nothing, since it no longer needs Quantic.

And look at that answer. Microsoft goes ex-dividend on 2026-10-08, *today*, inside the window. The
answer says no company does. Every figure in it is one a tool returned, so the run is `answered`. The
provenance check verifies figures, not claims. That's the line the design draws, and here is what's
on the other side of it, in a real run.

## What changed from the Go version

- **Alembic instead of goose**, with `autocommit=False` found by measuring, and the same `flock`.
- **The rate-limit retry is an HTTP transport under the SDK**, which answers with a JSON-RPC error
  when it gives up, because raising made the SDK cancel the call.
- **`Research` is filled in place** by the loop, because a Python function returns or raises, not
  both.
- **No `cmp.Or`**: dataclass defaults. **No timer and `select`**: `asyncio.sleep` is cancellable.
- **`no_data`'s table rebuild in an ordinary transaction**, on a connection that never turns foreign
  keys on.
- **One check fewer**: `phase != 'done'` in the resume claim, which nothing could fail.
- **Two validator checks more**: weekdays next to a date, and ranges of days.

## What I'm taking into milestone 9

- Measure a library's transactions before trusting them; then measure its locking. And measure a
  guess about why, before writing it down: mine was wrong.
- Know what an SDK does with the errors you care about: this one turned a rate limit into "your
  mistake".
- In a task group, raising doesn't return an error to the caller; it cancels the caller.
- Test the shortest backoff schedule, and the largest retry number.
- In Python a list passed in is shared, always. Make it the design, or copy it.
- A conditional `UPDATE` and its `rowcount` is a claim, no lock needed.
- A check nothing can fail is a check to remove.
- The validator checks figures. A wrong claim with right figures gets through.
- Which date is "today", the agent's or the data's, is an open question.
- Milestone 9 is the first with no Go version to port: the worker pool.

---

**Previous:** [Lesson 07 — A memory that can be audited](07-a-memory-that-can-be-audited.md) ·
**Next:** [Lesson 09 — One GPU, many calls](09-one-gpu-many-calls.md)
