"""A Week Ahead run's week, recorded when it starts.

A run's week used to be only the one after the day it started, worked out
again wherever it was needed. Written on a Monday for the week under way
(--week), a run would be read back as next week's. NULL, for every earlier
run, keeps that rule: weekahead.week_of.
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute("ALTER TABLE runs ADD COLUMN week_start TEXT")  # ISO date, a Monday


def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN week_start")
