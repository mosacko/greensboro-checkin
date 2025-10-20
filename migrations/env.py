from dotenv import load_dotenv
load_dotenv()

from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import os

config = context.config

# Use DATABASE_URL from env (Heroku/local)
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Normalize heroku's 'postgres://' to 'postgresql://'
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    config.set_main_option("sqlalchemy.url", db_url)
# ---------------------

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base + models so metadata is loaded
from app.database import Base  # noqa
import app.models  # noqa

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
