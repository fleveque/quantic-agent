import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quantic_agent.agent import Call
from quantic_agent.provenance import Kind, Manifest, check_prose
from quantic_agent.store import Draft, NotFoundError, State, Store

CALENDAR = (
    '{"from":"2026-10-06","days":10,"stocks":[{"symbol":"MSFT","ex_dividend_date":"2026-10-08"}]}'
)


def open_store(tmp_path: Path) -> Store:
    """A real file, not :memory:, so WAL and locking behave as in production."""
    return Store(tmp_path / "agent.db")


def calls() -> list[Call]:
    return [
        Call(
            tool="dividend_calendar",
            arguments={"days": 200},
            result="error: at most 120",
            failed=True,
        ),
        Call(
            tool="dividend_calendar",
            arguments={"days": 10},
            result=CALENDAR,
            duration=timedelta(milliseconds=312),
        ),
    ]


def test_a_run_round_trips(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "next 10 days?", "qwen3.5:9b")
        for seq, call in enumerate(calls()):
            db.record_call(run_id, seq, call)
        findings = check_prose("MSFT on Oct 8, in 3 days", Manifest([]))
        db.finish(
            run_id, State.UNVERIFIED, draft=Draft("MSFT on Oct 8, in 3 days", False, findings)
        )

        run = db.run(run_id)

    assert (run.kind, run.input, run.model, run.state) == (
        "research",
        "next 10 days?",
        "qwen3.5:9b",
        State.UNVERIFIED,
    )
    assert run.finished_at is not None
    # The audit log comes back in the order it was written, exactly.
    assert run.calls == calls()
    assert run.draft is not None
    assert run.draft.findings == findings
    assert run.draft.findings[0].kind is Kind.DATE
    # Only the successful call feeds the manifest.
    assert [r.result for r in run.records()] == [CALENDAR]


def test_a_stored_draft_can_be_rechecked(tmp_path: Path) -> None:
    # A stored run is checked later against exactly what the agent saw.
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.record_call(run_id, 0, calls()[1])
        db.finish(run_id, State.ANSWERED, draft=Draft("MSFT goes ex-dividend on Oct 8.", False, []))
        run = db.run(run_id)

    assert run.draft is not None
    assert check_prose(run.draft.content, Manifest(run.records())) == []
    assert [f.text for f in check_prose("and Apple on Oct 9", Manifest(run.records()))] == ["Oct 9"]


def test_migrations_apply_once(tmp_path: Path) -> None:
    open_store(tmp_path).close()
    # Opening the same file again finds the schema current and changes nothing.
    with open_store(tmp_path) as db:
        db.start_run("research", "q", "m")
    with sqlite3.connect(tmp_path / "agent.db") as raw:
        assert raw.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    # SQLite ignores REFERENCES unless foreign keys are switched on, for each
    # connection. This proves the setting reached the one that wrote.
    with open_store(tmp_path) as db, pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.record_call(999, 0, calls()[0])


def test_a_call_is_recorded_once(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.record_call(run_id, 0, calls()[0])
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.record_call(run_id, 0, calls()[1])


def test_finish_is_all_or_nothing(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        # A state the CHECK constraint refuses: the draft insert succeeds, then
        # the run update fails, and the draft must not survive it.
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            db.finish(run_id, "nonsense", draft=Draft("text", False, []))  # type: ignore[arg-type]
        run = db.run(run_id)

    assert run.state is State.RUNNING
    assert run.draft is None


def test_a_run_finishes_once(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, State.FAILED, "the server went away")
        with pytest.raises(NotFoundError, match="not running"):
            db.finish(run_id, State.ANSWERED)
        assert db.run(run_id).error == "the server went away"


def test_runs_newest_first(tmp_path: Path) -> None:
    times = iter(datetime(2026, 10, 7, 9, minute, tzinfo=UTC) for minute in range(10))
    with Store(tmp_path / "agent.db", now=lambda: next(times)) as db:
        first = db.start_run("research", "first", "m")
        second = db.start_run("research", "second", "m")
        db.record_call(second, 0, calls()[1])
        runs = db.runs(10)

    assert [(r.id, r.input, r.call_count) for r in runs] == [
        (second, "second", 1),
        (first, "first", 0),
    ]
    # 9:00 went to the migration's applied_at; the first run started at 9:01,
    # and comes back as an aware datetime in UTC.
    assert runs[1].started_at == datetime(2026, 10, 7, 9, 1, tzinfo=UTC)


def test_a_missing_run(tmp_path: Path) -> None:
    with open_store(tmp_path) as db, pytest.raises(NotFoundError):
        db.run(42)


def test_concurrent_writers_wait_their_turn(tmp_path: Path) -> None:
    # Several threads, each with its own connection, as several processes
    # would have: SQLite allows one writer at a time, and the busy timeout
    # makes the others wait instead of failing.
    open_store(tmp_path).close()
    errors: list[BaseException] = []

    def write() -> None:
        try:
            with open_store(tmp_path) as db:
                for _ in range(20):
                    run_id = db.start_run("research", "q", "m")
                    db.record_call(run_id, 0, calls()[1])
                    db.finish(run_id, State.ANSWERED, draft=Draft("x", False, []))
        except BaseException as err:
            errors.append(err)

    threads = [threading.Thread(target=write) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with open_store(tmp_path) as db:
        assert len(db.runs(1000)) == 160


def test_processes_opening_a_new_database(tmp_path: Path) -> None:
    # Several processes opening the same new database at once: each must find
    # the schema created exactly once. Real processes, because that's where
    # the collision is: without the lock, measured at 5 failed opens in 80.
    for round in range(8):
        path = tmp_path / f"round-{round}" / "agent.db"
        code = f"from quantic_agent.store import Store; Store({str(path)!r}).close()"
        procs = [
            subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.PIPE, text=True)
            for _ in range(4)
        ]
        for p in procs:
            _, err = p.communicate()
            assert p.returncode == 0, err
