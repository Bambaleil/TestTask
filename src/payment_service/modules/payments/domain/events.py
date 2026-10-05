"""Контракты событий платежа без зависимости от брокера и сериализатора."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from payment_service.core.contracts import JsonValue
from payment_service.core.events.models import OutboxEvent
from payment_service.modules.payments.domain.constants import NEW_TOPIC, Currency, PaymentStatus


@dataclass(frozen=True, kw_only=True)
class PaymentEvent:
    """Описывает конкретную прикладную попытку обработки платежа."""

    event_id: UUID
    payment_id: UUID
    attempt: int = 1
    version: int = 1

    def as_payload(self) -> dict[str, JsonValue]:
        """Возвращает JSON-совместимое тело с неизменным идентификатором события."""
        return {
            "event_id": str(self.event_id),
            "payment_id": str(self.payment_id),
            "attempt": self.attempt,
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class WebhookPayload:
    """Передаёт финальный результат в порт доставки уведомлений."""

    event_id: UUID
    payment_id: UUID
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    metadata: dict[str, JsonValue]
    processed_at: datetime

    def as_payload(self) -> dict[str, JsonValue]:
        """Возвращает JSON с точной суммой и датой обработки в ISO 8601."""
        return {
            "event_id": str(self.event_id),
            "payment_id": str(self.payment_id),
            "status": self.status.value,
            "amount": str(self.amount),
            "currency": self.currency.value,
            "metadata": self.metadata,
            "processed_at": self.processed_at.isoformat(),
        }


def new_payment_event(payment_id: UUID, attempt: int = 1) -> OutboxEvent:
    """Создаёт событие обработки для атомарного сохранения с платежом.

    Args:
        payment_id: Идентификатор созданного платежа.
        attempt: Номер следующей прикладной попытки.

    Returns:
        Событие Outbox для маршрута payments.new.

    """
    event = PaymentEvent(event_id=uuid4(), payment_id=payment_id, attempt=attempt)
    return OutboxEvent(
        id=event.event_id,
        aggregate_id=payment_id,
        topic=NEW_TOPIC,
        payload=event.as_payload(),
    )
