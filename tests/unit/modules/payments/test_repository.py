from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from payment_service.core.db.connection import SessionFactory
from payment_service.core.errors.exceptions import PersistenceConflictError
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.tables import PaymentRecord as Payment
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.exceptions import (
    IdempotencyConflictError,
    PaymentNotFoundError,
)
from payment_service.modules.payments.repository import PaymentRepository


@pytest.mark.parametrize("conflict", [False, True])
async def test_create(
    sessions: SessionFactory, payment_data: PaymentCreate, conflict: bool
) -> None:
    """Сохраняет один платёж и одно событие при повторении ключа."""
    service = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    first = await service.create(payment_data.to_command(), "order-123")
    if conflict:
        changed = payment_data.model_copy(update={"description": "Другая оплата"})
        with pytest.raises(IdempotencyConflictError):
            await service.create(changed.to_command(), "order-123")
    else:
        second = await service.create(payment_data.to_command(), "order-123")
        assert second.id == first.id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Payment)) == 1
        events = list(await session.scalars(select(OutboxEvent)))
        assert len(events) == 1
        assert events[0].payload["payment_id"] == str(first.id)
        assert events[0].published_at is None


class TestTransactionRollback:
    """Проверки атомарности создания платежа и записи Outbox."""

    async def test_create(self, sessions: SessionFactory, payment_data: PaymentCreate) -> None:
        """Откатить платёж, если запись события завершилась ошибкой."""
        with patch(
            "payment_service.modules.payments.dao.sqlalchemy.OutboxDAO.add",
            side_effect=RuntimeError,
        ):
            with pytest.raises(RuntimeError):
                await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
                    payment_data.to_command(), "rollback"
                )
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Payment)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0


@pytest.mark.parametrize("exists", [False, True])
async def test_get(sessions: SessionFactory, payment_data: PaymentCreate, exists: bool) -> None:
    """Возвращает существующий платёж и явно обработать отсутствующий UUID."""
    service = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    if exists:
        created = await service.create(payment_data.to_command(), "get-test")
        payment = await service.get(created.id)
        assert payment.id == created.id
        assert payment.amount == payment_data.amount
        assert payment.metadata == payment_data.metadata
    else:
        with pytest.raises(PaymentNotFoundError):
            await service.get(uuid4())


class TestUnrelatedPersistenceConflict:
    """Проверки конфликта хранения, не вызванного конкурентным клиентским запросом."""

    async def test_create(self, sessions: SessionFactory, payment_data: PaymentCreate) -> None:
        """Сохраняет исходную ошибку, если после конфликта нет платежа с таким ключом."""
        error = PersistenceConflictError()
        with patch(
            "payment_service.modules.payments.dao.sqlalchemy.PaymentDAO.add", side_effect=error
        ):
            with pytest.raises(PersistenceConflictError) as raised:
                await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
                    payment_data.to_command(), "unrelated-conflict"
                )
        assert raised.value is error
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Payment)) == 0
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
