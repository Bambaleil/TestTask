"""Общие фикстуры: изолированная SQLite и детерминированные адаптеры."""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from payment_service.core.db.connection import SessionFactory, create_session_factory
from payment_service.core.db.models import Base
from payment_service.modules.payments.dao.models import PaymentCreate
from tests.fakes import ServiceSettings


@pytest.fixture
async def sessions() -> AsyncIterator[SessionFactory]:
    """Создаёт отдельную базу в памяти для каждого теста."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.fixture
def settings() -> ServiceSettings:
    """Возвращает настройки без чтения локального файла окружения."""
    return ServiceSettings(
        _env_file=None,
        api_key="test-api-key-at-least-16-chars",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        rabbitmq_url="amqp://test:test@localhost/",
        retry_base_delay=2,
    )


@pytest.fixture
def payment_data() -> PaymentCreate:
    """Возвращает валидный запрос с дополнительными данными."""
    return PaymentCreate(
        amount=Decimal("123.45"),
        currency="RUB",
        description="Тестовая оплата",
        metadata={"order_id": "order-123"},
        webhook_url=HttpUrl("https://merchant.example/webhook"),
    )
