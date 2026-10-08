"""Pull requests: where a run's post went for review (milestone 12).

One pull request per run at most. Its state is the agent's last look at it:
open, merged, or closed without merging. A merge is the reviewer's approval
and a close their rejection, recorded in reviews when the agent syncs.
"""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE pull_requests (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL UNIQUE REFERENCES runs (id),
            repo        TEXT    NOT NULL,                 -- owner/name
            number      INTEGER NOT NULL,
            url         TEXT    NOT NULL,
            branch      TEXT    NOT NULL,
            period      TEXT    NOT NULL,                 -- the post's: 2026-W42
            state       TEXT    NOT NULL CHECK (state IN ('open', 'merged', 'closed')),
            opened_at   TEXT    NOT NULL,
            decided_at  TEXT,
            UNIQUE (repo, number)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE pull_requests")
