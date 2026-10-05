import asyncio
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from payment_service.core.db.connection import SessionFactory
from payment_service.core.db.models import Base
from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.sqlalchemy import OutboxDAO as OutboxRepository
from payment_service.modules.payments.dao.sqlalchemy import PaymentDAO
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.tables import PaymentRecord as Payment
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.entities import Payment as PaymentEntity
from payment_service.modules.payments.domain.exceptions import IdempotencyConflictError
from payment_service.modules.payments.repository import PaymentRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("conflict", [False, True])
async def test_create(
    sessions: SessionFactory,
    payment_data: PaymentCreate,
    conflict: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Конкурентные запросы создают один платёж; изменённое тело получает конфликт."""
    barrier = asyncio.Barrier(2)
    original_get = PaymentDAO.get_by_key

    async def simultaneous_get(repository: PaymentDAO, key: str) -> PaymentEntity | None:
        """Дать обоим запросам увидеть отсутствие ключа до конкурентных INSERT."""
        result = await original_get(repository, key)
        if result is None:
            await barrier.wait()
        return result

    monkeypatch.setattr(PaymentDAO, "get_by_key", simultaneous_get)
    service = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    first, second = await asyncio.gather(
        service.create(payment_data.to_command(), "concurrent-key"),
        service.create(
            payment_data.model_copy(update={"description": "Другой заказ"}).to_command()
            if conflict
            else payment_data.to_command(),
            "concurrent-key",
        ),
        return_exceptions=True,
    )
    if conflict:
        assert sum(isinstance(result, IdempotencyConflictError) for result in [first, second]) == 1
        assert sum(isinstance(result, PaymentEntity) for result in [first, second]) == 1
    else:
        assert isinstance(first, PaymentEntity)
        assert isinstance(second, PaymentEntity)
        assert first.id == second.id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Payment)) == 1
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1


async def test_get_pending(sessions: SessionFactory, payment_data: PaymentCreate) -> None:
    """SKIP LOCKED позволяет второму диспетчеру взять другой набор событий."""
    service = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    await service.create(payment_data.to_command(), str(uuid4()))
    await service.create(payment_data.to_command(), str(uuid4()))
    async with sessions() as first, first.begin(), sessions() as second, second.begin():
        locked = await OutboxRepository(first).get_pending(utcnow(), 1)
        other = await OutboxRepository(second).get_pending(utcnow(), 2)
        assert len(locked) == len(other) == 1
        assert locked[0].id != other[0].id


async def test_upgrade(postgres_engine: AsyncEngine) -> None:
    """Проверяет совпадение схемы начальной миграции с моделями SQLAlchemy."""

    def compare(connection: Connection) -> None:
        """Сравнить reflection настоящего PostgreSQL с декларативными моделями."""
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []

    async with postgres_engine.connect() as connection:
        await connection.run_sync(compare)
