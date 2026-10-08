from unittest.mock import patch
from uuid import uuid4

import pytest

from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, PaymentStatus
from payment_service.modules.payments.domain.events import PaymentEvent, WebhookPayload
from payment_service.modules.payments.domain.exceptions import InvalidEventError
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate
from tests.fakes import FakeGateway, FakeWebhooks, MemoryUnitOfWorkFactory


class TestInconsistentState:
    """Проверки несовпадения сообщения с долговечным состоянием платежа и Outbox."""

    @pytest.mark.parametrize(
        "mode", ["missing-payment", "wrong-aggregate", "wrong-topic", "unprocessed-result"]
    )
    async def test_process(self, payment_data: PaymentCreate, mode: str) -> None:
        """Не оплачивает и не уведомляет клиента при нарушении сохранённых контрактов."""
        factory = MemoryUnitOfWorkFactory()
        payment = await PaymentRepository(factory).create(
            payment_data.to_command(), "corrupt-state"
        )
        stored = next(iter(factory.state.events.values()))
        event = PaymentEvent(event_id=stored.id, payment_id=payment.id, attempt=1)
        if mode == "missing-payment":
            factory.state.payments.pop(payment.id)
        elif mode == "wrong-aggregate":
            stored.aggregate_id = uuid4()
        elif mode == "wrong-topic":
            stored.topic = DEAD_TOPIC
        else:
            factory.state.payments[payment.id].status = PaymentStatus.SUCCEEDED
        gateway, webhooks = FakeGateway(), FakeWebhooks()
        with pytest.raises(InvalidEventError):
            await PaymentProcessor(factory, gateway, webhooks, 2).process(event)
        assert gateway.calls == 0
        assert webhooks.calls == []
        assert len(factory.state.events) == 1
        assert factory.state.events[stored.id].consumed_at is None
        assert factory.state.events[stored.id].last_error is None


class TestPreviouslyDeliveredWebhook:
    """Проверки завершения события при уже сохранённом успешном уведомлении."""

    async def test_process(self, payment_data: PaymentCreate) -> None:
        """Закрывает попытку и очищает ошибку без повторной оплаты и HTTP-уведомления."""
        factory = MemoryUnitOfWorkFactory()
        repository = PaymentRepository(factory)
        payment = await repository.create(payment_data.to_command(), "already-delivered")
        saved = factory.state.payments[payment.id]
        saved.status = PaymentStatus.SUCCEEDED
        saved.processed_at = utcnow()
        saved.webhook_delivered_at = utcnow()
        saved.last_error = "TimeoutError"
        stored = next(iter(factory.state.events.values()))
        gateway, webhooks = FakeGateway(), FakeWebhooks()
        await PaymentProcessor(factory, gateway, webhooks, 2).process(
            PaymentEvent(event_id=stored.id, payment_id=payment.id, attempt=1)
        )
        assert gateway.calls == 0
        assert webhooks.calls == []
        assert (await repository.get(payment.id)).last_error is None
        assert factory.state.events[stored.id].consumed_at is not None
        assert len(factory.state.events) == 1


class TestConcurrentDelivery:
    """Проверки сбоя текущего уведомления после успешной доставки другим consumer."""

    async def test_process(self, payment_data: PaymentCreate) -> None:
        """Не создаёт retry или DLQ для события, уже завершённого другой транзакцией."""
        factory = MemoryUnitOfWorkFactory()
        repository = PaymentRepository(factory)
        payment = await repository.create(payment_data.to_command(), "concurrent-delivery")
        stored = next(iter(factory.state.events.values()))
        gateway, webhooks = FakeGateway(), FakeWebhooks()

        async def concurrent_delivery(url: str, payload: WebhookPayload) -> None:
            """Сохраняет чужое подтверждение прежде, чем текущий HTTP-запрос падает."""
            assert url == payment.webhook_url
            assert payload.payment_id == payment.id
            factory.state.events[stored.id].consumed_at = utcnow()
            factory.state.payments[payment.id].webhook_delivered_at = utcnow()
            raise TimeoutError

        with patch.object(webhooks, "send", side_effect=concurrent_delivery) as send:
            await PaymentProcessor(factory, gateway, webhooks, 2).process(
                PaymentEvent(event_id=stored.id, payment_id=payment.id, attempt=1)
            )
        send.assert_awaited_once()
        assert gateway.calls == 1
        assert len(factory.state.events) == 1
        result = await repository.get(payment.id)
        assert result.status == PaymentStatus.SUCCEEDED
        assert result.webhook_delivered_at is not None
        assert result.last_error is None
