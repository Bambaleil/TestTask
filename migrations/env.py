"""Запуск миграций Alembic через асинхронный движок SQLAlchemy."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from payment_service.core.settings import DatabaseSettings
from payment_service.schema import get_metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = get_metadata()


def run_migrations_offline() -> None:
    """Сформировать SQL миграции без подключения к базе данных."""
    context.configure(
        url=DatabaseSettings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнить миграции внутри синхронного контекста Alembic."""
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Подключиться к БД и передать соединение адаптеру Alembic."""
    engine = create_async_engine(
        DatabaseSettings().database_url.get_secret_value(), poolclass=NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif config.attributes.get("connection") is not None:
    do_run_migrations(config.attributes["connection"])
else:
    asyncio.run(run_migrations_online())
