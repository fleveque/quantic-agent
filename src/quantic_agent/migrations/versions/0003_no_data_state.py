"""A run whose research gathered nothing ends in its own state, no_data,
instead of writing an answer about nothing.

Adding a value to a CHECK constraint means rebuilding the table: SQLite can't
alter a constraint. This is SQLite's documented recipe
(sqlite.org/lang_altertable.html, section 7): create the new table, copy, drop
the old one, rename. tool_calls and drafts reference runs, so dropping it
needs foreign keys off, and they are: the store migrates on a connection of
its own that never turns them on. The recipe ends by checking that every
reference still points at a row.
"""

from alembic import op

revision = "0003"
down_revision = "0002"

_COLUMNS = "id, kind, input, model, state, error, started_at, finished_at, phase, tokens, exhausted"


def _rebuild(states: str) -> None:
    """Rebuilds runs with state limited to states, keeping every row."""
    op.execute(f"""
        CREATE TABLE runs_new (
            id          INTEGER PRIMARY KEY,
            kind        TEXT    NOT NULL,
            input       TEXT    NOT NULL,
            model       TEXT    NOT NULL,
            state       TEXT    NOT NULL CHECK (state IN ({states})),
            error       TEXT,
            started_at  TEXT    NOT NULL,
            finished_at TEXT,
            phase       TEXT    NOT NULL DEFAULT 'research'
                CHECK (phase IN ('research', 'write', 'done')),
            tokens      INTEGER NOT NULL DEFAULT 0,
            exhausted   TEXT    CHECK (exhausted IN ('calls', 'tokens'))
        )
    """)
    op.execute(f"INSERT INTO runs_new ({_COLUMNS}) SELECT {_COLUMNS} FROM runs")
    op.execute("DROP TABLE runs")
    op.execute("ALTER TABLE runs_new RENAME TO runs")
    broken = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if broken:
        raise RuntimeError(f"rebuilding runs broke references: {broken}")


def upgrade() -> None:
    _rebuild("'running', 'answered', 'unverified', 'failed', 'interrupted', 'no_data'")


def downgrade() -> None:
    # The old CHECK has no no_data: those runs go back to what they were
    # before this migration, failed.
    op.execute(
        "UPDATE runs SET state = 'failed', error = coalesce(error, 'research gathered no data') "
        "WHERE state = 'no_data'"
    )
    _rebuild("'running', 'answered', 'unverified', 'failed', 'interrupted'")
