from logging.config import fileConfig

from alembic import context
from flask import current_app


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = current_app.extensions["migrate"].db.metadata


def get_engine_url() -> str:
    engine = current_app.extensions["migrate"].db.engine
    return str(engine.url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = current_app.extensions["migrate"].db.engine
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
