"""Создание асинхронного подключения и фабрики сессий."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from payment_service.core.settings import DatabaseSettings

SessionFactory = async_sessionmaker[AsyncSession]


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Создаёт пул подключений с проверкой соединения перед использованием."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
    )


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    """Создаёт фабрику независимых сессий для каждой операции."""
    return async_sessionmaker(engine, expire_on_commit=False)
