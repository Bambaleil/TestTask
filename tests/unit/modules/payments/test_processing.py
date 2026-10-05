from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from payment_service.core.db.connection import SessionFactory
from payment_service.modules.payments.dao.models import PaymentCreate, PaymentEventMessage
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC, PaymentStatus
from payment_service.modules.payments.domain.exceptions import InvalidEventError
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from tests.fakes import FakeGateway, FakeWebhooks


@pytest.mark.parametrize(
    ("outcome", "gateway_failures", "webhook_failures", "expected_status", "dead"),
    [
        (PaymentStatus.SUCCEEDED, 0, 0, "succeeded", False),
        (PaymentStatus.FAILED, 0, 0, "failed", False),
        (PaymentStatus.SUCCEEDED, 0, 1, "succeeded", False),
        (PaymentStatus.SUCCEEDED, 0, 3, "succeeded", True),
        (PaymentStatus.SUCCEEDED, 1, 0, "succeeded", False),
        (PaymentStatus.SUCCEEDED, 3, 0, "failed", True),
    ],
)
async def test_process(
    sessions: SessionFactory,
    payment_data: PaymentCreate,
    outcome: PaymentStatus,
    gateway_failures: int,
    webhook_failures: int,
    expected_status: str,
    dead: bool,
) -> None:
    """Проверяет оплату, дедупликацию, retry, экспоненциальную задержку и DLQ."""
    service = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    payment = await service.create(payment_data.to_command(), "processing-test")
    gateway = FakeGateway(outcome, gateway_failures)
    webhooks = FakeWebhooks(webhook_failures)
    processor = PaymentProcessor(
        PaymentUnitOfWorkFactory(sessions), gateway, webhooks, retry_base_delay=2
    )
    for attempt in range(1, 4):
        async with sessions() as session:
            stored = await session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.topic == NEW_TOPIC, OutboxEvent.consumed_at.is_(None)
                )
            )
        if stored is None:
            break
        event = PaymentEventMessage.model_validate(stored.payload).to_event()
        assert event.attempt == attempt
        if attempt > 1:
            delay = (stored.available_at - stored.created_at).total_seconds()
            assert abs(delay - 2 ** (attempt - 1)) < 0.1
        await processor.process(event)
        calls = gateway.calls, len(webhooks.calls)
        await processor.process(event)
        assert calls == (gateway.calls, len(webhooks.calls))
    result = await service.get(payment.id)
    assert result.status == expected_status
    assert result.processed_at is not None
    assert (result.webhook_delivered_at is None) == dead
    assert gateway.calls == min(gateway_failures + 1, 3)
    assert len({payload.event_id for payload in webhooks.calls}) <= 1
    async with sessions() as session:
        events = list(await session.scalars(select(OutboxEvent)))
        dead_events = [event for event in events if event.topic == DEAD_TOPIC]
        assert len(dead_events) == int(dead)
        assert len(events) == (4 if dead else gateway_failures + webhook_failures + 1)
        if dead:
            assert dead_events[0].payload["attempt"] == 3
            assert result.last_error == "TimeoutError"
        else:
            assert result.last_error is None


class TestInvalidEvent:
    """Проверки сообщений с подменёнными идентификаторами или счётчиком попыток."""

    @pytest.mark.parametrize("mode", ["unknown", "payment-id", "attempt"])
    async def test_process(
        self, sessions: SessionFactory, payment_data: PaymentCreate, mode: str
    ) -> None:
        """Отклонить сообщение, которое не соответствует сохранённому событию."""
        payment = await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
            payment_data.to_command(), "invalid-event"
        )
        async with sessions() as session:
            stored = (await session.scalars(select(OutboxEvent))).one()
        event = PaymentEventMessage.model_validate(stored.payload).to_event()
        updates = {
            "unknown": {"event_id": uuid4()},
            "payment-id": {"payment_id": uuid4()},
            "attempt": {"attempt": 3},
        }
        event = replace(event, **updates[mode])
        gateway = FakeGateway()
        processor = PaymentProcessor(PaymentUnitOfWorkFactory(sessions), gateway, FakeWebhooks(), 2)
        with pytest.raises(InvalidEventError):
            await processor.process(event)
        assert gateway.calls == 0
        assert payment.status == PaymentStatus.PENDING
