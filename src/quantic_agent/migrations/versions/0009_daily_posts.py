"""The daily X posts (milestone 16): each version drafted, and the issue it
went into for the author.

A daily run records every version it wrote for each company, with the facts
it was written from and what its checks found: none, for a version that can
be proposed. Versions are numbered as the issue numbers them, the proposed
ones first. posted_at is when --sync last saw its box ticked in the issue,
NULL when it isn't.

One issue per run at most, its state as the agent last saw it.
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE proposals (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL REFERENCES runs (id),
            symbol      TEXT    NOT NULL,
            angle       TEXT    NOT NULL CHECK (angle IN ('change', 'ex_dividend', 'yield')),
            version     INTEGER NOT NULL,                 -- 1, 2, … as the issue shows it
            text        TEXT    NOT NULL,
            facts       TEXT    NOT NULL,                 -- JSON: what it was written from
            problems    TEXT    NOT NULL,                 -- JSON: empty when proposed
            posted_at   TEXT,                             -- ticked in the issue, last seen
            created_at  TEXT    NOT NULL,
            UNIQUE (run_id, symbol, version)
        )
    """)
    op.execute("""
        CREATE TABLE issues (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL UNIQUE REFERENCES runs (id),
            repo        TEXT    NOT NULL,                 -- owner/name
            number      INTEGER NOT NULL,
            url         TEXT    NOT NULL,
            state       TEXT    NOT NULL CHECK (state IN ('open', 'closed')),
            opened_at   TEXT    NOT NULL,
            closed_at   TEXT,
            UNIQUE (repo, number)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE issues")
    op.execute("DROP TABLE proposals")
