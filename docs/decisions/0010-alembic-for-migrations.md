# 0010 — Migrations with Alembic

**Status:** accepted · **Date:** 2026-10-08

## Context

Milestone 7 applied the store's schema with about thirty hand-written lines: numbered SQL files
shipped in the package, each applied once in its own transaction, recorded in `schema_migrations`,
with a file lock (`flock`) so processes opening a new database take turns. The Go version did the
same at its milestone 7 and moved to a library, `pressly/goose`, at its milestone 8, to have done both.

Milestone 8 needs two more migrations, one of which rebuilds a table, and the same question comes
up. The Python choices:

- **Alembic**, the migration tool most Python projects with a SQL database use. It runs on
  SQLAlchemy, brings it as a dependency (about 18 MB installed), and writes migrations as Python
  files, each naming the one before it, with `upgrade()` and `downgrade()`. Fully typed.
- **yoyo-migrations**, the closest to goose: plain `.sql` files with `.rollback.sql` companions, a
  CLI, 172 KB and no dependencies. Untyped, so the strict type check would need a wrapper. It locks
  with a row in a table, which a crashed process leaves behind until `yoyo break-lock`.
- **Stay hand-written**: no dependency, no downgrades.

## Decision

**The store migrates with Alembic.** The store keeps using `sqlite3` for everything else: Alembic and
SQLAlchemy only run migrations, on a connection of their own, opened when the store opens and closed
before it's used.

That connection is opened with `connect_args={"autocommit": False}`. Measured before deciding: with
`sqlite3` in its default mode, a migration that created a table and then failed left the table behind
with `alembic_version` unchanged, so every later open would fail on it. With `autocommit=False`
(Python 3.12+), the whole migration rolls back.

The `flock` stays. Alembic has no lock for SQLite, and without ours, four processes opening a new
database collided in 47 and 50 of 80 opens, against 5 of 80 for the hand-written code; with it,
0 of 400.

## Consequences

- Every migration has a `downgrade()`, and a test takes the schema down to nothing and back up.
- Migrations are Python files in `quantic_agent/migrations/versions/`, run by `env.py`, found
  through `quantic_agent:migrations` wherever the package is installed (checked from a built wheel).
- A database created by milestone 7 is handed over once, in one transaction: Alembic's `stamp`
  records the version `schema_migrations` held, and the old table is dropped.
- The lockfile grows from 43 packages to 47: Alembic, SQLAlchemy, Mako and MarkupSafe.
- The migration connection never turns foreign keys on, which the table rebuild in `0003` relies on;
  the store's own connection always does.
