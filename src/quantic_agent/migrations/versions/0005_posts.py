"""Posts: a Week Ahead run's files, one per locale (milestone 11).

A run that writes a post records each locale's file, and whether it is ready
to publish or held, with what held it. A held translation is kept too, as
the reply it was: a reviewer can see what the check refused (design §3.5).
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE posts (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL REFERENCES runs (id),
            locale      TEXT    NOT NULL,
            status      TEXT    NOT NULL CHECK (status IN ('ready', 'held')),
            content     TEXT    NOT NULL,                 -- the file, or the reply that held it
            problems    TEXT    NOT NULL,                 -- JSON: why it is held
            created_at  TEXT    NOT NULL,
            UNIQUE (run_id, locale)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE posts")
