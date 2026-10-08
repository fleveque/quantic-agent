"""Reviews, embeddings, and the examples a writer was shown (milestone 10).

A reviewer approves or rejects a run's answer. An approved answer is
embedded, and becomes style memory: the writer of a later run is shown the
most similar ones as examples of the house voice (design §3.4). Which examples
a run was shown is recorded, as everything that reaches the model is (N3).
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    # One verdict per run's answer; reviewing again replaces it.
    op.execute("""
        CREATE TABLE reviews (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL UNIQUE REFERENCES runs (id),
            verdict     TEXT    NOT NULL CHECK (verdict IN ('approved', 'rejected')),
            note        TEXT,
            decided_at  TEXT    NOT NULL
        )
    """)
    # Text as vectors: float32, little-endian, dims of them. source_kind and
    # source_id say what the text is; for now only an approved answer, whose
    # source_id is its run. One vector per text and embedding model.
    op.execute("""
        CREATE TABLE embeddings (
            id          INTEGER PRIMARY KEY,
            source_kind TEXT    NOT NULL CHECK (source_kind IN ('answer')),
            source_id   INTEGER NOT NULL,
            model       TEXT    NOT NULL,
            dims        INTEGER NOT NULL,
            vector      BLOB    NOT NULL,
            text        TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            UNIQUE (source_kind, source_id, model)
        )
    """)
    # The approved answers a run's writer was shown, and how similar each was.
    op.execute("""
        CREATE TABLE examples (
            id          INTEGER PRIMARY KEY,
            run_id      INTEGER NOT NULL REFERENCES runs (id),
            example_run INTEGER NOT NULL REFERENCES runs (id),
            score       REAL    NOT NULL,
            UNIQUE (run_id, example_run)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE examples")
    op.execute("DROP TABLE embeddings")
    op.execute("DROP TABLE reviews")
