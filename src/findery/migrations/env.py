"""Alembic environment. Runs both from the `alembic` command and from the app itself."""

from alembic import context
from sqlalchemy import create_engine

from findery.config import load_settings
from findery.db.tables import Base

# The app passes the database URL explicitly; the `alembic` command takes it from settings.
url = context.config.get_main_option("sqlalchemy.url") or f"sqlite:///{load_settings().db_path}"

engine = create_engine(url)
with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # SQLite cannot alter most things in place; batch mode rebuilds the table instead.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
