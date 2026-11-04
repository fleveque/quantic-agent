"""The posts each daily writer was shown as examples (milestone 19).

Before writing about a company, the writer is shown up to three posts the
author published earlier (decision 0022): a version ticked as written, or a
post read from a "posted" comment, with the version it started from when it
was edited. Each row is one example as the writer saw it, text and draft
copied, so the record stays true if the comment is edited later.
"""

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE post_examples (
            id              INTEGER PRIMARY KEY,
            run_id          INTEGER NOT NULL REFERENCES runs (id),
            symbol          TEXT    NOT NULL,                 -- the company being written
            position        INTEGER NOT NULL,                 -- 1, 2, … as the writer saw them
            example_run     INTEGER NOT NULL REFERENCES runs (id),
            example_symbol  TEXT    NOT NULL,
            angle           TEXT,                             -- the example's, if known
            text            TEXT    NOT NULL,                 -- as posted, without the link
            drafted         TEXT,                             -- the version it was edited from
            posted_at       TEXT    NOT NULL,                 -- when it went out, as last read
            UNIQUE (run_id, symbol, position)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE post_examples")
