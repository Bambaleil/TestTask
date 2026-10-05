from decimal import Decimal

import pytest

from payment_service.modules.payments.domain.constants import Currency, PaymentStatus
from payment_service.modules.payments.domain.entities import CreatePaymentCommand
from payment_service.modules.payments.domain.events import PaymentEvent
from payment_service.modules.payments.domain.exceptions import IdempotencyConflictError
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from tests.fakes import FakeGateway, FakeWebhooks, MemoryUnitOfWorkFactory


def payment_command() -> CreatePaymentCommand:
    """Возвращает чистую доменную команду без DTO фреймворка."""
    return CreatePaymentCommand(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="Заказ",
        metadata={},
        webhook_url="https://merchant.example/webhook",
    )


@pytest.mark.parametrize("conflict", [False, True], ids=["same-request", "different-request"])
async def test_create(conflict: bool) -> None:
    """Проверяет идемпотентность через порты в памяти, без SQLAlchemy и сети."""
    factory = MemoryUnitOfWorkFactory()
    repository = PaymentRepository(factory)
    command = payment_command()
    first = await repository.create(command, "order-1")
    if conflict:
        from dataclasses import replace

        with pytest.raises(IdempotencyConflictError):
            await repository.create(replace(command, description="Другой заказ"), "order-1")
    else:
        second = await repository.create(command, "order-1")
        assert first.id == second.id
    assert len(factory.state.payments) == len(factory.state.events) == 1


class TestAtomicWrite:
    """Проверки атомарности бизнес-операции через независимый Unit of Work."""

    async def test_create(self) -> None:
        """Не фиксирует платёж, если сохранение события не завершилось."""
        factory = MemoryUnitOfWorkFactory(fail_event_write=True)
        with pytest.raises(RuntimeError):
            await PaymentRepository(factory).create(payment_command(), "rollback")
        assert factory.state.payments == {}
        assert factory.state.events == {}


@pytest.mark.parametrize("webhook_failures", [0, 1], ids=["delivered", "retry-notification"])
async def test_process(webhook_failures: int) -> None:
    """Сохраняет результат и не повторяет оплату при retry webhook без ORM-tracking."""
    factory = MemoryUnitOfWorkFactory()
    payment = await PaymentRepository(factory).create(payment_command(), "process")
    gateway, webhooks = FakeGateway(), FakeWebhooks(webhook_failures)
    processor = PaymentProcessor(factory, gateway, webhooks, 2)
    for attempt in range(1, webhook_failures + 2):
        stored = next(event for event in factory.state.events.values() if event.consumed_at is None)
        event = PaymentEvent(event_id=stored.id, payment_id=payment.id, attempt=attempt)
        await processor.process(event)
    result = factory.state.payments[payment.id]
    assert result.status == PaymentStatus.SUCCEEDED
    assert result.webhook_delivered_at is not None
    assert gateway.calls == 1
    assert len(webhooks.calls) == webhook_failures + 1
