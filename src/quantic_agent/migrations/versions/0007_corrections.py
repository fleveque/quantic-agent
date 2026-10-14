"""Corrections: what the reviewer changed in a post before merging it
(milestone 14).

A merged pull request publishes the files on its branch, which can differ
from the ones the agent wrote: the reviewer edits them. Each section that
differs is recorded with the text the agent wrote and the text published,
and the pull request records the merge commit they were read from. A merged
pull request with no merge commit recorded hasn't been read yet, whatever
its age: the next sync reads it.
"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute("ALTER TABLE pull_requests ADD COLUMN merge_commit TEXT")
    op.execute("""
        CREATE TABLE corrections (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL REFERENCES runs (id),
            locale      TEXT    NOT NULL,
            section     TEXT    NOT NULL,                 -- summary, watch, data, frontmatter, file
            drafted     TEXT    NOT NULL,                 -- what the agent wrote
            published   TEXT,                             -- NULL: the file was left out
            created_at  TEXT    NOT NULL,
            UNIQUE (run_id, locale, section)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE corrections")
    op.execute("ALTER TABLE pull_requests DROP COLUMN merge_commit")
