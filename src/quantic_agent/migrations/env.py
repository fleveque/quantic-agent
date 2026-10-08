"""How Alembic runs this package's migrations: on the connection the store
hands it (quantic_agent.store), each migration in its own transaction, so one
that fails partway leaves nothing behind and isn't recorded."""

from alembic import context

context.configure(
    connection=context.config.attributes["connection"],
    transaction_per_migration=True,
)
with context.begin_transaction():
    context.run_migrations()
