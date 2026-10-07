"""The agent's history in SQLite: every run, every tool call it made (the audit
log of design N3), and what it produced.

It uses the standard library's sqlite3, synchronously. A write takes a few
milliseconds, so the async agent calls it directly. That has a useful side:
a cancelled task stops only at an await, so a save that's under way when
Ctrl-C arrives always finishes, and an interrupted run is still recorded.

The schema is a series of Alembic migrations shipped in the package
(quantic_agent/migrations), brought up to date when the store opens.
"""

import fcntl
import json
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import sqlalchemy
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from quantic_agent.agent import Call, Limit
from quantic_agent.provenance import Finding, Kind, Record


class StoreError(Exception):
    """Anything that went wrong reading or writing the database."""


class NotFoundError(StoreError):
    """No row matched."""


class NotResumableError(StoreError):
    """The run can't be resumed: it doesn't exist, it finished with an
    answer, or it is running."""


class State(StrEnum):
    """Where a run stands. The database refuses any other value (the CHECK
    constraint on runs.state)."""

    RUNNING = "running"
    ANSWERED = "answered"  # every figure traced to a tool call
    UNVERIFIED = "unverified"  # answered, with figures no tool returned
    FAILED = "failed"  # stopped by an error
    INTERRUPTED = "interrupted"  # stopped by Ctrl-C or SIGTERM
    NO_DATA = "no_data"  # research gathered nothing to write from


class Phase(StrEnum):
    """How far a run has got (design §3.1). A run is saved at the end of each
    phase, and resumes from the phase it was in."""

    RESEARCH = "research"  # calling tools
    WRITE = "write"  # research done; writing the answer
    DONE = "done"  # answered


# The states a run can be resumed from: those that end a run without an answer.
RESUMABLE = (State.INTERRUPTED, State.FAILED, State.NO_DATA)


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
    phase: Phase
    tokens: int  # model tokens used, both phases
    exhausted: Limit | None  # the budget that cut research short, if one did
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
                migrate(path)
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

    def checkpoint(self, run_id: int, phase: Phase, tokens: int, exhausted: Limit | None) -> None:
        """Records that a running run has finished a phase: from here on,
        resuming it starts at phase. tokens and exhausted are what research
        spent, and the budget that stopped it, if one did."""
        cursor = self._db.execute(
            "UPDATE runs SET phase = ?, tokens = ?, exhausted = ? WHERE id = ? AND state = ?",
            (phase, tokens, exhausted, run_id, State.RUNNING),
        )
        if cursor.rowcount != 1:
            raise NotFoundError(f"run {run_id} is not running")

    def finish(
        self,
        run_id: int,
        state: State,
        error: str | None = None,
        draft: Draft | None = None,
        *,
        tokens: int | None = None,
    ) -> None:
        """Ends a run: its state, the error that stopped it, its draft if it
        produced one, and the tokens it used in all (None leaves them as
        checkpointed). One transaction, so a run is never marked answered
        without its draft, or the reverse. A run with a draft is done; one
        without stays in its phase, to resume from."""
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
                "UPDATE runs SET state = ?, error = ?, finished_at = ?, "
                "tokens = coalesce(?, tokens), phase = iif(?, ?, phase) "
                "WHERE id = ? AND state = ?",
                (
                    state,
                    error,
                    self._stamp(),
                    tokens,
                    draft is not None,
                    Phase.DONE,
                    run_id,
                    State.RUNNING,
                ),
            )
            if cursor.rowcount != 1:
                raise NotFoundError(f"run {run_id} is not running")

    def resume(self, run_id: int) -> Run:
        """Claims a run that stopped before answering (interrupted, failed, or
        with no data), marks it running again, and returns it with its calls.

        The claim is one UPDATE that only matches a resumable run. SQLite runs
        one write at a time, so if two processes resume the same run at once,
        the second finds it running already, matches nothing, and gets
        NotResumableError: the condition is the claim.
        """
        placeholders = ", ".join("?" * len(RESUMABLE))
        cursor = self._db.execute(
            "UPDATE runs SET state = ?, error = NULL, finished_at = NULL "
            f"WHERE id = ? AND state IN ({placeholders})",
            (State.RUNNING, run_id, *RESUMABLE),
        )
        if cursor.rowcount != 1:
            raise NotResumableError(
                f"run {run_id} can't be resumed: only an interrupted, failed or "
                "no-data run without an answer can be"
            )
        return self.run(run_id)

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
            "SELECT r.id, r.kind, r.input, r.model, r.state, r.phase, r.tokens, r.exhausted, "
            "r.error, r.started_at, r.finished_at, "
            "(SELECT COUNT(*) FROM tool_calls c WHERE c.run_id = r.id) "
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
                phase=Phase(phase),
                tokens=tokens,
                exhausted=Limit(exhausted) if exhausted else None,
                error=error or "",
                started_at=datetime.fromisoformat(started),
                finished_at=datetime.fromisoformat(finished) if finished else None,
                call_count=count,
            )
            for (
                id,
                kind,
                input,
                model,
                state,
                phase,
                tokens,
                exhausted,
                error,
                started,
                finished,
                count,
            ) in rows
        ]


# The migrations, as package:directory: found wherever the package is installed.
MIGRATIONS = "quantic_agent:migrations"


def alembic_config(connection: sqlalchemy.Connection, location: str = MIGRATIONS) -> Config:
    """Alembic's configuration for the migrations at location, run on
    connection. The store uses it to migrate; tests use it to take the schema
    down and up again."""
    config = Config()
    config.set_main_option("script_location", location)
    config.attributes["connection"] = connection
    return config


def migrate(path: Path, location: str = MIGRATIONS) -> None:
    """Brings the schema up to date: Alembic applies every migration the
    database hasn't recorded in alembic_version, in order.

    It runs on a connection of its own, through SQLAlchemy, with
    autocommit=False: then sqlite3 has a transaction open whenever SQL runs,
    and a migration that fails partway is rolled back whole. Left in its
    default mode, sqlite3 starts no transaction before CREATE TABLE, and a
    failed migration left its first tables behind (measured; lesson 08).
    Foreign keys stay off on this connection, as SQLite leaves them, which the
    table rebuild in 0003 needs.

    Store calls it while holding the migration lock; on its own, it doesn't
    take one.
    """
    engine = sqlalchemy.create_engine(
        f"sqlite:///{path}", poolclass=sqlalchemy.NullPool, connect_args={"autocommit": False}
    )
    try:
        with engine.connect() as connection:
            config = alembic_config(connection, location)
            _adopt(connection, config)
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def _adopt(connection: sqlalchemy.Connection, config: Config) -> None:
    """Hands a database migrated by milestone 7's hand-written code over to
    Alembic. Those record applied versions in schema_migrations, which Alembic
    doesn't read: left alone, it would see none and run 0001 again, failing on
    "table runs already exists". So, once, in one transaction: record the
    latest version in alembic_version (Alembic's stamp), and drop the old
    table. A database without schema_migrations is left alone."""
    with connection.begin():
        legacy = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).first()
        if legacy is None:
            return
        latest = connection.exec_driver_sql("SELECT max(version) FROM schema_migrations").scalar()
        # 1 was 0001_runs_calls_drafts.sql, now the revision named "0001".
        MigrationContext.configure(connection).stamp(
            ScriptDirectory.from_config(config), f"{latest:04d}"
        )
        connection.exec_driver_sql("DROP TABLE schema_migrations")


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
