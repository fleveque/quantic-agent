"""What was posted on X, and the review, read from a daily issue's comments
(milestone 18, decision 0020).

A tick says a version was posted as written. A post edited or written from
scratch, and the review that suggested it, come back as comments: kind
"posted" (the company, the version it started from or NULL, the text as
posted) or "review" (whole). One row per GitHub comment: an edited comment
replaces its row's text, and a deleted one keeps its row, as corrections
keep what was read.

An issue's comments are read on every sync while it's open, and once more
after it's closed: comments_read_at is when that last read was. A closed
issue with none hasn't had it yet, however old, so the first sync after
this migration reads the issues closed before it.
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute("ALTER TABLE issues ADD COLUMN comments_read_at TEXT")
    op.execute("""
        CREATE TABLE issue_comments (
            id            INTEGER PRIMARY KEY,
            run_id        INTEGER NOT NULL REFERENCES runs (id),
            comment_id    INTEGER NOT NULL UNIQUE,          -- GitHub's
            url           TEXT    NOT NULL,
            kind          TEXT    NOT NULL CHECK (kind IN ('posted', 'review')),
            symbol        TEXT,                             -- posted only
            version       INTEGER,                          -- posted from a version, if any
            text          TEXT    NOT NULL,
            commented_at  TEXT    NOT NULL,                 -- GitHub's updated_at
            read_at       TEXT    NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE issue_comments")
    op.execute("ALTER TABLE issues DROP COLUMN comments_read_at")
