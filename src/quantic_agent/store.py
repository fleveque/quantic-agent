"""The agent's history in SQLite: every run, every tool call it made (the audit
log of design N3), and what it produced.

It uses the standard library's sqlite3, synchronously. A write takes a few
milliseconds, so the async agent calls it directly. That has a useful side:
a cancelled task stops only at an await, so a save that's under way when
Ctrl-C arrives always finishes, and an interrupted run is still recorded.

The schema is a series of numbered SQL files shipped in the package
(quantic_agent/migrations), applied in order when the store opens.
"""

import fcntl
import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Any, Self

from quantic_agent.agent import Call
from quantic_agent.provenance import Finding, Kind, Record


class StoreError(Exception):
    """Anything that went wrong reading or writing the database."""


class NotFoundError(StoreError):
    """No row matched."""


class State(StrEnum):
    """Where a run stands. The database refuses any other value (the CHECK
    constraint in the first migration)."""

    RUNNING = "running"
    ANSWERED = "answered"  # every figure traced to a tool call
    UNVERIFIED = "unverified"  # answered, with figures no tool returned
    FAILED = "failed"  # stopped by an error
    INTERRUPTED = "interrupted"  # stopped by Ctrl-C or SIGTERM


@dataclass
class Draft:
    """What a run produced, and what the provenance check found in it."""

    content: str
    truncated: bool
    findings: list[Finding]
    created_at: datetime | None = None


@dataclass
class Run:
    """One run as stored. calls and draft are filled in by Store.run."""

    id: int
    kind: str
    input: str
    model: str
    state: State
    error: str
    started_at: datetime
    finished_at: datetime | None
    call_count: int
    calls: list[Call] = field(default_factory=lambda: list[Call]())
    draft: Draft | None = None

    def records(self) -> list[Record]:
        """The run's successful calls as provenance records: exactly what its
        manifest was built from. Re-checking a stored draft against them shows
        what the agent saw then, whatever the tools would return today."""
        return [Record(c.tool, c.result) for c in self.calls if not c.failed]


class Store:
    """The agent's database, opened by `with Store(path) as store:`.

    One connection, used from one thread: sqlite3 refuses to share a
    connection across threads unless told to. The settings that SQLite keeps
    per connection are applied here, once: foreign keys (ignored otherwise),
    write-ahead logging (readers don't block the writer), and a busy timeout
    (wait for another writer's lock instead of failing at once).
    """

    def __init__(self, path: Path | str, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        path = Path(path)
        # 0o700: the run history is the operator's alone.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # autocommit=True: nothing happens in a transaction unless BEGIN says
        # so. The default mode opens transactions implicitly, and its
        # executescript() commits whatever is pending first, which would let a
        # migration apply halfway.
        self._db = sqlite3.connect(path, timeout=5.0, autocommit=True)
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            with _locked(path.with_name(path.name + ".lock")):
                # Switching a new database to WAL takes an exclusive lock of
                # its own, so it waits its turn with the migrations: outside
                # the lock it collided with another process's migration.
                self._db.execute("PRAGMA journal_mode = WAL")
                self._migrate()
        except BaseException:
            self._db.close()
            raise

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Generator[None]:
        """Everything in the block, or none of it. IMMEDIATE takes the write
        lock at the start, so two writers queue on the busy timeout instead of
        both starting and one failing when it tries to write."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")

    def _migrate(self) -> None:
        """Applies every migration the database hasn't seen, in order, each in
        its own transaction: it applies completely and is recorded, or not at
        all."""
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {v for (v,) in self._db.execute("SELECT version FROM schema_migrations")}
        migrations = files("quantic_agent").joinpath("migrations")
        # 0001_..., 0002_...: the names are the order.
        for migration in sorted(migrations.iterdir(), key=lambda m: m.name):
            if not migration.name.endswith(".sql"):
                continue
            version = int(migration.name.split("_", 1)[0])
            if version in applied:
                continue
            with self._transaction():
                self._db.executescript(migration.read_text())
                self._db.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, self._stamp()),
                )

    def _stamp(self) -> str:
        """The current time as stored: ISO 8601 in UTC, which sorts as text in
        the same order as time."""
        return self._now().astimezone(UTC).isoformat()

    def start_run(self, kind: str, input: str, model: str) -> int:
        """Records a run as running, and returns its id."""
        cursor = self._db.execute(
            "INSERT INTO runs (kind, input, model, state, started_at) VALUES (?, ?, ?, ?, ?)",
            (kind, input, model, State.RUNNING, self._stamp()),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def record_call(self, run_id: int, seq: int, call: Call) -> None:
        """Appends one tool call to a run's audit log. Called as each call
        completes, not at the end, so a run that crashes or is stopped still
        leaves a record of everything it did."""
        self._db.execute(
            "INSERT INTO tool_calls "
            "(run_id, seq, tool, arguments, result, failed, duration_ms, called_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                call.tool,
                json.dumps(call.arguments),
                call.result,
                call.failed,
                round(call.duration.total_seconds() * 1000),
                self._stamp(),
            ),
        )

    def finish(
        self, run_id: int, state: State, error: str | None = None, draft: Draft | None = None
    ) -> None:
        """Ends a run: its state, the error that stopped it, and its draft if
        it produced one, in one transaction, so a run is never marked answered
        without its draft, or the reverse."""
        with self._transaction():
            if draft is not None:
                self._db.execute(
                    "INSERT INTO drafts (run_id, content, truncated, findings, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        run_id,
                        draft.content,
                        draft.truncated,
                        json.dumps([asdict(f) for f in draft.findings]),
                        self._stamp(),
                    ),
                )
            # Only a running run can finish: updating by id and state together
            # makes "finish twice" an error instead of a quiet overwrite.
            cursor = self._db.execute(
                "UPDATE runs SET state = ?, error = ?, finished_at = ? WHERE id = ? AND state = ?",
                (state, error, self._stamp(), run_id, State.RUNNING),
            )
            if cursor.rowcount != 1:
                raise NotFoundError(f"run {run_id} is not running")

    def runs(self, limit: int = 20) -> list[Run]:
        """The most recent runs, newest first, without their calls."""
        return self._query("ORDER BY r.id DESC LIMIT ?", (limit,))

    def run(self, run_id: int) -> Run:
        """One run, with its calls in the order they were made, and its draft."""
        found = self._query("WHERE r.id = ?", (run_id,))
        if not found:
            raise NotFoundError(f"run {run_id}")
        run = found[0]
        rows = self._db.execute(
            "SELECT tool, arguments, result, failed, duration_ms "
            "FROM tool_calls WHERE run_id = ? ORDER BY seq",
            (run_id,),
        )
        run.calls = [
            Call(
                tool=tool,
                arguments=json.loads(arguments),
                result=result,
                failed=bool(failed),
                duration=timedelta(milliseconds=ms),
            )
            for tool, arguments, result, failed, ms in rows
        ]
        row = self._db.execute(
            "SELECT content, truncated, findings, created_at FROM drafts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is not None:  # no draft: the run failed or was stopped before answering
            content, truncated, findings, created = row
            run.draft = Draft(
                content=content,
                truncated=bool(truncated),
                findings=[_finding(f) for f in json.loads(findings)],
                created_at=datetime.fromisoformat(created),
            )
        return run

    def _query(self, tail: str, params: tuple[Any, ...]) -> list[Run]:
        rows = self._db.execute(
            "SELECT r.id, r.kind, r.input, r.model, r.state, r.error, r.started_at, "
            "r.finished_at, (SELECT COUNT(*) FROM tool_calls c WHERE c.run_id = r.id) "
            f"FROM runs r {tail}",
            params,
        )
        return [
            Run(
                id=id,
                kind=kind,
                input=input,
                model=model,
                state=State(state),
                error=error or "",
                started_at=datetime.fromisoformat(started),
                finished_at=datetime.fromisoformat(finished) if finished else None,
                call_count=count,
            )
            for id, kind, input, model, state, error, started, finished, count in rows
        ]


def _finding(stored: dict[str, Any]) -> Finding:
    return Finding(
        text=stored["text"],
        offset=stored["offset"],
        kind=Kind(stored["kind"]),
        value=stored["value"],
    )


@contextmanager
def _locked(path: Path) -> Generator[None]:
    """An exclusive lock on the file at path, held for the block.

    This is how processes take turns at migrating. SQLite's own locks protect
    one statement or one transaction, but bringing a schema up to date is
    several (create the version table, then one per migration), and two
    processes interleaving them collide. SQLite has no server to hold a lock,
    so the lock is a file next to the database. flock(2) locks are released
    by the kernel when the process exits, however it exits, so a crashed
    process never leaves the lock held.
    """
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # waits for whoever holds it
        yield
    # Closing the file released the lock.
