# Lesson 07 — A memory that can be audited

**Milestone 7** — every research run is kept in SQLite: the run, every tool call it made as each
one completes (the audit log of design N3), and the answer with what the provenance check found.
`--runs` lists them; `--run N` shows one and re-checks its answer against the tool results it was
given, whatever the tools would say today. In Go this was the first external dependency, a
connection pool to tame, and a context to detach so an interrupted run could still be saved. In
Python, most of that dissolved: SQLite comes with the language, there's one connection, and a
synchronous save can't be cancelled halfway. What took the work was transactions, a lock, and my
own tests.

---

## What landed

```
$ uv run quantic-agent --research "What goes ex-dividend this week?"
tool dividend_calendar {"days": 7} → 544 bytes (295ms)
...
quantic-agent: run 1 answered
$ uv run quantic-agent --runs
RUN  STARTED           STATE     CALLS  QUESTION
1    2026-10-07 23:47  answered  1      What goes ex-dividend this week?
$ uv run quantic-agent --run 1
...
provenance, re-checked now: every figure traces to a stored tool result
```

`quantic_agent/store.py` holds three tables (`runs`, `tool_calls`, `drafts`) created by one
migration, `migrations/0001_runs_calls_drafts.sql`, the Go version's file unchanged. A run is
`running` until it ends `answered`, `unverified` (figures with no source), `failed` or `interrupted`,
and the database refuses any other state.

## SQLite comes with the language

Go's milestone 7 added the project's first dependency, `modernc.org/sqlite`, chosen because it's pure
Go and keeps the binary static; CI gained a build with cgo turned off to protect that. Python ships
`sqlite3` in the standard library, compiled C included, and there's no static binary to protect.
Nothing to add to `pyproject.toml`.

Go's `database/sql` hands out a *pool* of connections, so settings SQLite keeps per connection
(foreign keys, the busy timeout) had to travel in the connection string to reach every one. Python's
`sqlite3.connect` is one connection. The settings are applied once, after connecting:

```python
self._db = sqlite3.connect(path, timeout=5.0, autocommit=True)
self._db.execute("PRAGMA foreign_keys = ON")
```

`timeout=5.0` is the busy timeout: wait up to five seconds for another writer's lock instead of
failing at once. Foreign keys are off unless asked for, as in Go, and a test proves the setting reached
the connection that wrote: a tool call for a run that doesn't exist is refused.

## Transactions, and a mode that commits behind your back

A migration has to apply completely or not at all, and `finish` writes a run's draft and its final
state together. Both need transactions, and `sqlite3` has three modes for them. Its default, kept
for compatibility, opens transactions implicitly before a write, and its `executescript`, which runs a
whole SQL file, commits whatever is pending first:

```
legacy: in_transaction after INSERT: True
legacy: in_transaction after executescript: False (it committed)
```

So a migration run with `executescript` in the default mode could apply halfway. With
`autocommit=True`, nothing is in a transaction unless `BEGIN` says so, and `executescript` stays inside
it, so even a `CREATE TABLE` rolls back:

```
in transaction after executescript: True
table exists after rollback: 0
```

The store's transactions are a context manager, written as a generator:

```python
@contextmanager
def _transaction(self) -> Generator[None]:
    self._db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        self._db.execute("ROLLBACK")
        raise
    self._db.execute("COMMIT")
```

`@contextmanager` turns a generator into something `with` can use: the code before `yield` runs on
entering the block, and if the block raises, the exception is thrown in at the `yield`. Go deferred a
`tx.Rollback()` that does nothing after a commit. `IMMEDIATE` takes the write lock at `BEGIN`, so two
writers queue on the busy timeout instead of both starting and one failing at its first write.

`finish` relies on it: a run is never `answered` without its draft. The test gives `finish` a state
the `CHECK` constraint refuses, so the draft is written and then the update fails. The draft has to
be gone afterwards. Without the transaction, it isn't.

## Migrating, by hand, with a lock from the start

Go wrote its migrations by hand at milestone 7, then switched to the goose library at milestone 8. I
followed the same path: thirty lines that read the numbered SQL files shipped in the package (with
`importlib.resources`, as the evaluation cases in milestone 5), apply each one the database hasn't
recorded in `schema_migrations`, and record it, in one transaction.

Go found a gap in its hand-written version, and recorded it before fixing it a milestone later:
several processes opening a *new* database at once collide. I measured mine before deciding whether to
port the gap or the fix, with four real processes opening each new database, 20 rounds:

```
== without the lock
5 of 80 opens failed
   sqlite3.OperationalError: database is locked
   sqlite3.OperationalError: table runs already exists
```

"Table runs already exists" is two processes both deciding the first migration hadn't been applied.
SQLite's own locks protect one statement or one transaction, and bringing a schema up to date is
several. So the fix came now: an exclusive lock on a file next to the database, held while migrating.

```python
with path.open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)  # waits for whoever holds it
    yield
```

`flock` locks belong to the open file, and the kernel releases them when the process exits, however
it exits, so a crash never leaves the lock held. Measured again:

```
== with the lock
1 of 80 opens failed
   sqlite3.OperationalError: database is locked
```

One left. The `PRAGMA journal_mode = WAL` that switches the database to write-ahead logging was before
the lock, and switching a new database's journal takes an exclusive lock of its own. Moved inside:

```
0 of 200 opens failed
0 of 200 opens failed
```

The test runs the same race with real processes, eight rounds of four. With the lock removed, it
failed three times out of three.

## A save that can't be cancelled

When Ctrl-C stops a run, the run should be recorded as `interrupted`. Go's problem was that the
context that carried the cancellation also cancelled the save, so it saved with
`context.WithoutCancel`, a context that keeps the values and drops the cancellation.

The Python store is synchronous: `sqlite3` blocks, and the async agent calls it directly. A write
takes milliseconds, so the event loop doesn't notice, and it brings a property for free. A task can
only be cancelled where it `await`s, so synchronous code runs to the end even in a task that's being
cancelled:

```python
except asyncio.CancelledError:
    # Recorded, then passed on. finish() is synchronous, so it runs to the
    # end even in a cancelled task: cancellation only lands at an await.
    finish(store.State.INTERRUPTED)
    raise
```

The test sends a real `SIGTERM` while a tool call hangs, and checks the stored run. Without the
`finish` there, the run is still `running`, with no end time.

The deadline moved for this too. It used to wrap the whole command, but to record a run that ran out
of time as `failed` and one that was stopped as `interrupted`, the research path needs to see which
happened. With `asyncio.timeout` inside the `try`, a deadline arrives as `TimeoutError` and a signal
as `CancelledError`, two different `except` clauses.

## My tests wrote into my home directory

Go's lesson 07 has a section about its tests writing three fake runs into the real
`~/.local/state/quantic-agent`, until a `TestMain` pointed them elsewhere. I read it before writing
this milestone, and made the same mistake anyway: the `--research` tests from milestones 5 and 6 now
record their runs, and nothing told them where. After the first full run of the suite:

```
(1, 'answered', 'next 10 days?', '2026-10-07T21:44:58.421544+00:00')
(2, 'failed', 'q', '2026-10-07T21:44:58.472864+00:00')
(3, 'unverified', 'q', '2026-10-07T21:44:58.503658+00:00')
```

Three fake runs, as in Go. The directory hadn't existed before the tests ran, so I deleted it. The fix
is an *autouse* fixture in `conftest.py`, which pytest applies to every test without being asked:

```python
@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "state" / "agent.db"
    monkeypatch.setenv("QUANTIC_AGENT_DB", str(db))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return db
```

`tmp_path` is a fresh directory per test; `monkeypatch.setenv` sets an environment variable for the
test and restores it after. A test that wants the path asks for `isolated_state` by name. Go's
`TestMain` ran once around the whole package; this runs around each test, so no two share a history
either.

## What the audit log can't see

One real run's answer said Apple goes ex-dividend "on **Tuesday, October 9**" and Iberdrola "on
**Wednesday, October 10**". The dates are right. The weekdays are not:

```
9 Friday
10 Saturday
```

No tool returned a weekday; the model made them up, and got both wrong. The provenance check reads
numbers and dates, not the names of days, so it passed, and `--run 1` re-checks it as clean. That's a
figure-like claim N1 should cover. Go's validator had the same blind spot. I've recorded it for
milestone 8, which takes on the validator's other gaps found in real runs.

## What changed from the Go version

- **No dependency**: `sqlite3` is in the standard library.
- **One connection**, settings applied once, where Go configured a pool through its connection string.
- **`autocommit=True` and `BEGIN IMMEDIATE`**, chosen after watching the default mode commit inside
  `executescript`.
- **The migration lock from the start**, with the WAL switch inside it, where Go added the lock at
  milestone 8.
- **A synchronous store**, so an interrupted run is saved without Go's `context.WithoutCancel`.
- **The research path has its own deadline**, to tell a timeout from an interruption.

## What I'm taking into milestone 8

- Read a library's transaction mode before trusting its transactions.
- Measure a race with real processes before deciding it doesn't matter, and again after fixing it.
- Synchronous code is the one thing a cancellation can't interrupt halfway.
- An autouse fixture for anything a test could touch outside its own directory, from the first test.
- Milestone 8 grows the loop: budgets, retries, a separate writer, resuming a stopped run, and the
  validator's gaps, now including weekdays.

---

**Previous:** [Lesson 06 — Every figure has a source](06-every-figure-has-a-source.md)
