import asyncio
from unittest.mock import Mock, patch

import pytest
from faststream.rabbit.message import RabbitMessage
from sqlalchemy import func, select

from payment_service.core.db.connection import SessionFactory
from payment_service.core.events.models import OutboxEvent
from payment_service.modules.payments.dao.sqlalchemy import OutboxDAO, PaymentDAO
from payment_service.modules.payments.dao.tables import OutboxRecord, PaymentRecord
from payment_service.modules.payments.dao.unit_of_work import (
    PaymentUnitOfWork,
    PaymentUnitOfWorkFactory,
)
from payment_service.modules.payments.domain.constants import PaymentStatus
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import PaymentEvent
from payment_service.modules.payments.handlers.rabbitmq import PaymentMessageHandler
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate
from tests.fakes import FakeGateway, FakeWebhooks

pytestmark = pytest.mark.integration


async def test_create(sessions: SessionFactory, payment_data: PaymentCreate) -> None:
    """Наблюдатель видит платёж и Outbox только вместе после commit общей сессии."""
    factory = PaymentUnitOfWorkFactory(sessions)
    flushed, release = asyncio.Event(), asyncio.Event()
    original_add = OutboxDAO.add
    used_sessions: list[object] = []
    original_payment_add = PaymentDAO.add

    async def add_payment(dao: PaymentDAO, payment: Payment) -> None:
        """Запоминает сессию после настоящего INSERT платежа."""
        used_sessions.append(dao.session)
        await original_payment_add(dao, payment)

    async def add_outbox(dao: OutboxDAO, event: OutboxEvent) -> None:
        """Останавливает общую транзакцию после обоих INSERT и до commit."""
        used_sessions.append(dao.session)
        await original_add(dao, event)
        flushed.set()
        await release.wait()

    with (
        patch.object(PaymentDAO, "add", new=add_payment),
        patch.object(OutboxDAO, "add", new=add_outbox),
    ):
        task = asyncio.create_task(
            PaymentRepository(factory).create(payment_data.to_command(), "atomic")
        )
        try:
            async with asyncio.timeout(3):
                await flushed.wait()
                assert used_sessions[0] is used_sessions[1]
                async with sessions() as observer:
                    assert (
                        await observer.scalar(select(func.count()).select_from(PaymentRecord)) == 0
                    )
                    assert (
                        await observer.scalar(select(func.count()).select_from(OutboxRecord)) == 0
                    )
                release.set()
                payment = await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
    async with sessions() as observer:
        assert await observer.scalar(select(func.count()).select_from(PaymentRecord)) == 1
        event = (await observer.scalars(select(OutboxRecord))).one()
        assert event.payment_id == payment.id


class TestCreateRollback:
    """Проверки отката настоящих INSERT в PostgreSQL при сбое до фиксации."""

    @pytest.mark.parametrize("failure", ["outbox", "commit", "cancel"])
    async def test_create(
        self, sessions: SessionFactory, payment_data: PaymentCreate, failure: str
    ) -> None:
        """Ошибка Outbox, commit или отмена задачи не оставляет ни одной из записей."""
        original_add = OutboxDAO.add
        expected = asyncio.CancelledError if failure == "cancel" else ConnectionError

        async def fail_add(dao: OutboxDAO, event: OutboxEvent) -> None:
            """Выбрасывает ошибку после отправки настоящего INSERT в базу."""
            await original_add(dao, event)
            raise expected

        target = (
            patch.object(PaymentUnitOfWork, "commit", side_effect=ConnectionError)
            if failure == "commit"
            else patch.object(OutboxDAO, "add", new=fail_add)
        )
        with target:
            with pytest.raises(expected):
                await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
                    payment_data.to_command(), "rollback"
                )
        async with sessions() as observer:
            assert await observer.scalar(select(func.count()).select_from(PaymentRecord)) == 0
            assert await observer.scalar(select(func.count()).select_from(OutboxRecord)) == 0


class TestRetryRollback:
    """Проверки одной транзакции для завершения попытки и записи retry или DLQ."""

    @pytest.mark.parametrize("attempt", [1, 3], ids=["retry", "dlq"])
    async def test_process_payment(
        self, sessions: SessionFactory, payment_data: PaymentCreate, attempt: int
    ) -> None:
        """Не ACK-ает сообщение и не завершает попытку, если запись продолжения падает."""
        factory = PaymentUnitOfWorkFactory(sessions)
        payment = await PaymentRepository(factory).create(
            payment_data.to_command(), "retry-rollback"
        )
        async with sessions() as session, session.begin():
            stored = (await session.scalars(select(OutboxRecord))).one()
            stored.payload = {**stored.payload, "attempt": attempt}
            event = PaymentEvent(event_id=stored.id, payment_id=payment.id, attempt=attempt)
        gateway = FakeGateway(failures=1)
        webhooks = FakeWebhooks()
        message = Mock(spec=RabbitMessage)
        original_add = OutboxDAO.add

        async def fail_add(dao: OutboxDAO, followup: OutboxEvent) -> None:
            """Срывает сохранение после INSERT retry/DLQ, чтобы проверить полный rollback."""
            await original_add(dao, followup)
            raise ConnectionError

        with patch.object(OutboxDAO, "add", new=fail_add):
            await PaymentMessageHandler(
                PaymentProcessor(factory, gateway, webhooks, 0.001), 0.001
            ).process_payment(event.as_payload(), message)
        message.nack.assert_awaited_once_with(requeue=True)
        message.ack.assert_not_awaited()
        async with sessions() as observer:
            persisted = (await observer.scalars(select(OutboxRecord))).one()
            assert persisted.consumed_at is None
            assert persisted.last_error is None
            assert (await PaymentRepository(factory).get(payment.id)).last_error is None
        # Новый экземпляр обработчика продолжает то же долговечное событие после сбоя.
        redelivered = Mock(spec=RabbitMessage)
        await PaymentMessageHandler(
            PaymentProcessor(factory, gateway, webhooks, 0.001), 0.001
        ).process_payment(event.as_payload(), redelivered)
        redelivered.ack.assert_awaited_once()
        redelivered.nack.assert_not_awaited()
        assert len(webhooks.calls) == 1
        async with sessions() as observer:
            assert await observer.scalar(select(func.count()).select_from(OutboxRecord)) == 1
            assert (await observer.get(OutboxRecord, event.event_id)).consumed_at is not None


class TestConcurrentProcessing:
    """Проверки PostgreSQL-блокировок при одновременной доставке одного события."""

    async def test_process(self, sessions: SessionFactory, payment_data: PaymentCreate) -> None:
        """Две конкурентные обработки оплачивают платёж и отправляют webhook один раз."""
        factory = PaymentUnitOfWorkFactory(sessions)
        payment = await PaymentRepository(factory).create(payment_data.to_command(), "parallel")
        async with sessions() as session:
            stored = (await session.scalars(select(OutboxRecord))).one()
        event = PaymentEvent(event_id=stored.id, payment_id=payment.id)
        gateway, webhooks = FakeGateway(), FakeWebhooks()
        original_charge = gateway.charge

        async def slow_charge(value: Payment) -> PaymentStatus:
            """Удерживает блокировку платежа, пока второй consumer начинает обработку."""
            await asyncio.sleep(0.02)
            return await original_charge(value)

        with patch.object(gateway, "charge", new=slow_charge):
            await asyncio.gather(
                PaymentProcessor(factory, gateway, webhooks, 0.001).process(event),
                PaymentProcessor(factory, gateway, webhooks, 0.001).process(event),
            )
        assert gateway.calls == 1
        assert len(webhooks.calls) == 1
        async with sessions() as observer:
            assert (await observer.get(OutboxRecord, event.event_id)).consumed_at is not None
            assert await observer.scalar(select(func.count()).select_from(OutboxRecord)) == 1
