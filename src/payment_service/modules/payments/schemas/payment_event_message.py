"""Валидация внешнего RabbitMQ-сообщения платёжного модуля."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from payment_service.modules.payments.domain.constants import MAX_ATTEMPTS
from payment_service.modules.payments.domain.events import PaymentEvent


class PaymentEventMessage(BaseModel):
    """Версионированное событие для обработки платежа."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(description="Стабильный идентификатор конкретной попытки обработки")
    payment_id: UUID = Field(description="Уникальный идентификатор платежа")
    attempt: int = Field(default=1, ge=1, le=MAX_ATTEMPTS, description="Номер попытки от 1 до 3")
    version: int = Field(default=1, ge=1, le=1, description="Версия контракта события")

    def to_event(self) -> PaymentEvent:
        """Преобразует валидированное сообщение в доменное событие."""
        return PaymentEvent(
            event_id=self.event_id,
            payment_id=self.payment_id,
            attempt=self.attempt,
            version=self.version,
        )
