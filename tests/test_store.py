import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from importlib.resources import as_file, files
from pathlib import Path

import pytest
import sqlalchemy
from alembic import command
from sqlalchemy.exc import OperationalError

from quantic_agent import memory, store
from quantic_agent.agent import Call, Limit
from quantic_agent.provenance import Kind, Manifest, check_prose
from quantic_agent.store import (
    Draft,
    NotFoundError,
    NotResumableError,
    NotReviewableError,
    Phase,
    State,
    Store,
)

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
    assert tables(tmp_path / "agent.db") == [
        "alembic_version",
        "drafts",
        "embeddings",
        "examples",
        "reviews",
        "runs",
        "tool_calls",
    ]
    assert version(tmp_path / "agent.db") == HEAD


# The latest migration.
HEAD = "0004"


def tables(path: Path) -> list[str]:
    with sqlite3.connect(path) as raw:
        rows = raw.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        return [name for (name,) in rows]


def version(path: Path) -> str:
    with sqlite3.connect(path) as raw:
        return raw.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def alembic(path: Path, step: str, revision: str) -> None:
    """Runs an Alembic command, upgrade or downgrade, on the database at path,
    on a connection set up as the store's own."""
    engine = sqlalchemy.create_engine(
        f"sqlite:///{path}", poolclass=sqlalchemy.NullPool, connect_args={"autocommit": False}
    )
    with engine.connect() as connection:
        getattr(command, step)(store.alembic_config(connection), revision)
    engine.dispose()


def test_every_migration_goes_down_and_up_again(tmp_path: Path) -> None:
    # A downgrade is code like any other: one that leaves a table behind
    # fails the way back up.
    path = tmp_path / "agent.db"
    open_store(tmp_path).close()

    alembic(path, "downgrade", "base")
    assert tables(path) == ["alembic_version"]

    alembic(path, "upgrade", "head")
    assert version(path) == HEAD


def test_a_failed_migration_leaves_nothing_behind(tmp_path: Path) -> None:
    # The package's migrations, and a fourth that creates a table and then
    # fails. Measured: in sqlite3's default mode, the table stayed, with
    # alembic_version unchanged, so every later open would fail on it.
    location = tmp_path / "migrations"
    with as_file(files("quantic_agent").joinpath("migrations")) as source:
        shutil.copytree(source, location, ignore=shutil.ignore_patterns("__pycache__"))
    (location / "versions" / "9999_broken.py").write_text(
        "from alembic import op\n"
        "revision = 'broken'\n"
        f"down_revision = {HEAD!r}\n"
        "def upgrade():\n"
        "    op.execute('CREATE TABLE half (x INTEGER)')\n"
        "    op.execute('this is not SQL')\n"
    )
    path = tmp_path / "agent.db"

    with pytest.raises(OperationalError, match="syntax error"):
        store.migrate(path, str(location))

    assert "half" not in tables(path)
    assert version(path) == HEAD


def milestone_7_database(path: Path) -> None:
    """A database as milestone 7 left it: the first migration's schema, and
    its versions in schema_migrations, which Alembic doesn't read. Two runs,
    one answered, one interrupted, each with a call; one draft."""
    Store(path).close()
    alembic(path, "downgrade", "0001")
    with sqlite3.connect(path) as raw:
        raw.executescript("""
            DROP TABLE alembic_version;
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            INSERT INTO schema_migrations VALUES (1, '2026-10-07T21:00:00+00:00');
            INSERT INTO runs (kind, input, model, state, started_at) VALUES
                ('research', 'answered', 'm', 'answered', '2026-10-07T21:01:00+00:00'),
                ('research', 'stopped', 'm', 'interrupted', '2026-10-07T21:02:00+00:00');
            INSERT INTO tool_calls
                (run_id, seq, tool, arguments, result, failed, duration_ms, called_at)
            VALUES
                (1, 0, 'dividend_calendar', '{}', '{}', 0, 5, '2026-10-07T21:01:01+00:00'),
                (2, 0, 'dividend_calendar', '{}', '{}', 0, 5, '2026-10-07T21:02:01+00:00');
            INSERT INTO drafts (run_id, content, truncated, findings, created_at)
                VALUES (1, 'text', 0, '[]', '2026-10-07T21:01:02+00:00');
        """)


def test_a_milestone_7_database_is_handed_over(tmp_path: Path) -> None:
    path = tmp_path / "agent.db"
    milestone_7_database(path)

    with Store(path) as db:
        runs = {r.input: r for r in db.runs()}
        # The rebuild of runs kept the rows that point at it, and they still
        # must point at a run.
        assert [c.tool for c in db.run(runs["stopped"].id).calls] == ["dividend_calendar"]
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            db.record_call(999, 0, calls()[0])

    assert "schema_migrations" not in tables(path)
    assert version(path) == HEAD
    # An answered run is done; an interrupted one can be resumed from research.
    assert (runs["answered"].phase, runs["stopped"].phase) == (Phase.DONE, Phase.RESEARCH)
    with sqlite3.connect(path) as raw:
        assert raw.execute("PRAGMA foreign_key_check").fetchall() == []


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
    # The first run started at 9:00, and comes back as an aware datetime in UTC.
    assert runs[1].started_at == datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


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


def test_a_checkpoint_is_where_a_run_resumes(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.record_call(run_id, 0, calls()[1])
        db.checkpoint(run_id, Phase.WRITE, 1500, Limit.CALLS)
        db.finish(run_id, State.INTERRUPTED)

        run = db.resume(run_id)

    assert (run.state, run.phase, run.tokens, run.exhausted) == (
        State.RUNNING,
        Phase.WRITE,
        1500,
        Limit.CALLS,
    )
    assert (run.error, run.finished_at) == ("", None)
    assert run.calls == [calls()[1]]


def test_a_draft_makes_a_run_done(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, State.ANSWERED, draft=Draft("x", False, []), tokens=2000)
        run = db.run(run_id)

        assert (run.phase, run.tokens) == (Phase.DONE, 2000)
        with pytest.raises(NotResumableError):
            db.resume(run_id)


@pytest.mark.parametrize("state", [State.FAILED, State.NO_DATA, State.INTERRUPTED])
def test_a_run_without_an_answer_can_be_resumed(tmp_path: Path, state: State) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, state, "why")
        assert db.resume(run_id).state is State.RUNNING


def test_a_running_or_missing_run_cant_be_resumed(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        with pytest.raises(NotResumableError):
            db.resume(run_id)
        with pytest.raises(NotResumableError):
            db.resume(42)


def test_only_one_resume_gets_the_run(tmp_path: Path) -> None:
    # Ten resumes of one run at once, each with its own connection, as ten
    # processes would have. The UPDATE's condition is the claim: one wins.
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, State.INTERRUPTED)
    won: list[int] = []
    lost: list[int] = []
    start = threading.Barrier(10)

    def resume(i: int) -> None:
        with open_store(tmp_path) as db:
            start.wait()
            try:
                db.resume(run_id)
                won.append(i)
            except NotResumableError:
                lost.append(i)

    threads = [threading.Thread(target=resume, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert (len(won), len(lost)) == (1, 9)


# ---- reviews and style memory ------------------------------------------------


def answered(db: Store, text: str = "MSFT goes ex-dividend on Oct 8.") -> int:
    run_id = db.start_run("research", "q", "m")
    db.finish(run_id, State.ANSWERED, draft=Draft(text, False, []))
    return run_id


def test_an_approved_answer_is_style_memory(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = answered(db)
        db.approve(run_id, "good tone", "embedder", [3.0, 4.0], "MSFT goes ex-dividend on Oct 8.")

        [stored] = db.memories("embedder")
        run = db.run(run_id)

    assert (stored.run_id, stored.text) == (run_id, "MSFT goes ex-dividend on Oct 8.")
    # Stored at unit length, as nearest() expects.
    assert list(stored.vector) == pytest.approx([0.6, 0.8])
    assert run.review is not None
    assert (run.review.verdict, run.review.note) == ("approved", "good tone")


def test_vectors_belong_to_their_model(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        db.approve(answered(db), "", "embedder", [1.0, 0.0], "text")
        assert db.memories("another-embedder") == []


def test_an_answer_with_unsourced_figures_cant_be_approved(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, State.UNVERIFIED, draft=Draft("in 180 days", False, []))
        with pytest.raises(NotReviewableError, match="unverified"):
            db.approve(run_id, "", "embedder", [1.0], "in 180 days")
        # Nothing was half-recorded.
        assert db.run(run_id).review is None


def test_a_run_without_an_answer_cant_be_reviewed(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = db.start_run("research", "q", "m")
        db.finish(run_id, State.FAILED, "gone")
        with pytest.raises(NotReviewableError, match="no answer"):
            db.reject(run_id, "")


def test_rejecting_takes_an_answer_out_of_memory(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        run_id = answered(db)
        db.approve(run_id, "", "embedder", [1.0, 0.0], "text")
        db.reject(run_id, "on reflection, no")

        assert db.memories("embedder") == []
        review = db.run(run_id).review
        assert review is not None
        assert review.verdict == "rejected"


def test_the_examples_a_writer_saw_are_recorded(tmp_path: Path) -> None:
    with open_store(tmp_path) as db:
        example = answered(db)
        db.approve(example, "", "embedder", [1.0, 0.0], "text")
        run_id = db.start_run("research", "q", "m")
        [match] = memory.nearest([1.0, 0.1], db.memories("embedder"), k=2)

        db.record_examples(run_id, [match])
        db.record_examples(run_id, [match])  # a resumed run writes again

        assert db.run(run_id).examples == [(example, pytest.approx(match.score))]
