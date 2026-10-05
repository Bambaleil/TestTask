from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from payment_service.core.db.connection import SessionFactory
from payment_service.core.events.outbox import OutboxDispatcher, OutboxOptions
from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.repository import PaymentRepository
from tests.fakes import FakePublisher, ServiceSettings


@pytest.mark.parametrize("failures", [0, 1])
async def test_dispatch_batch(
    sessions: SessionFactory, payment_data: PaymentCreate, settings: ServiceSettings, failures: int
) -> None:
    """Пометить событие опубликованным только после положительного подтверждения."""
    await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
        payment_data.to_command(), "outbox-test"
    )
    publisher = FakePublisher(failures)
    dispatcher = OutboxDispatcher(PaymentUnitOfWorkFactory(sessions), publisher, OutboxOptions())
    assert await dispatcher.dispatch_batch() == 1 - failures
    async with sessions() as session, session.begin():
        stored = (await session.scalars(select(OutboxEvent))).one()
        assert stored.publish_attempts == 1
        assert (stored.published_at is None) == bool(failures)
        if failures:
            assert stored.last_error == "ConnectionError"
            stored.available_at = utcnow() - timedelta(seconds=1)
    assert await dispatcher.dispatch_batch() == failures
    assert await dispatcher.dispatch_batch() == 0
    assert len(publisher.calls) == 1 + failures
    assert len({call[2] for call in publisher.calls}) == 1


class TestOutboxCommitFailure:
    """Проверки повторной публикации после сбоя БД вслед за broker confirm."""

    async def test_dispatch_batch(
        self, sessions: SessionFactory, payment_data: PaymentCreate, settings: ServiceSettings
    ) -> None:
        """После ошибки commit отправить то же событие повторно, не теряя его."""
        await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
            payment_data.to_command(), "commit-test"
        )
        publisher = FakePublisher()
        dispatcher = OutboxDispatcher(
            PaymentUnitOfWorkFactory(sessions), publisher, OutboxOptions()
        )
        with patch("sqlalchemy.orm.SessionTransaction.commit", side_effect=RuntimeError):
            with pytest.raises(RuntimeError):
                await dispatcher.dispatch_batch()
        async with sessions() as session:
            stored = (await session.scalars(select(OutboxEvent))).one()
            assert stored.published_at is None
        assert await dispatcher.dispatch_batch() == 1
        assert len(publisher.calls) == 2
        assert publisher.calls[0][2] == publisher.calls[1][2]


class TestDelayedEvent:
    """Проверки ожидания момента, назначенного для повторной попытки."""

    async def test_dispatch_batch(
        self, sessions: SessionFactory, payment_data: PaymentCreate, settings: ServiceSettings
    ) -> None:
        """Не публиковать событие раньше available_at."""
        await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
            payment_data.to_command(), "future-test"
        )
        async with sessions() as session, session.begin():
            stored = (await session.scalars(select(OutboxEvent))).one()
            stored.available_at = utcnow() + timedelta(hours=1)
        publisher = FakePublisher()
        assert (
            await OutboxDispatcher(
                PaymentUnitOfWorkFactory(sessions), publisher, OutboxOptions()
            ).dispatch_batch()
            == 0
        )
        assert publisher.calls == []
