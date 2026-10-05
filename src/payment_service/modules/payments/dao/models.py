"""Схемы запросов API, событий очереди и webhook-уведомлений."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from payment_service.modules.payments.domain.constants import MAX_ATTEMPTS, Currency, PaymentStatus
from payment_service.modules.payments.domain.entities import CreatePaymentCommand
from payment_service.modules.payments.domain.events import PaymentEvent

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]


class PaymentCreate(BaseModel):
    """Данные для создания платежа с точной десятичной суммой."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount: Money = Field(description="Положительная сумма, не более двух знаков после запятой")
    currency: Currency = Field(description="Валюта платежа: RUB, USD или EUR")
    description: str = Field(min_length=1, max_length=1000, description="Назначение платежа")
    metadata: dict[str, JsonValue] = Field(
        default_factory=dict, description="Дополнительные данные клиента"
    )
    webhook_url: HttpUrl = Field(max_length=2048, description="HTTP(S)-адрес получателя результата")

    def to_command(self) -> CreatePaymentCommand:
        """Передаёт нормализованные данные запроса в независимую бизнес-команду.

        Returns:
            Команда с нормализованным URL и точной десятичной суммой.

        """
        return CreatePaymentCommand(
            amount=self.amount,
            currency=self.currency,
            description=self.description,
            metadata=self.metadata,
            webhook_url=str(self.webhook_url),
        )

    def fingerprint(self) -> str:
        """Возвращает отпечаток доменной команды для сравнения запросов."""
        return self.to_command().fingerprint()


class PaymentAccepted(BaseModel):
    """Краткий ответ после принятия платежа в обработку."""

    payment_id: UUID = Field(description="Уникальный идентификатор платежа")
    status: PaymentStatus = Field(description="Текущий результат обработки платежа")
    created_at: datetime = Field(description="Момент принятия платежа в UTC")


class PaymentDetails(PaymentAccepted):
    """Полное представление платежа и результата доставки уведомления."""

    amount: Decimal = Field(description="Точная сумма; в JSON передаётся строкой")
    currency: Currency = Field(description="Валюта платежа: RUB, USD или EUR")
    description: str = Field(description="Назначение платежа")
    metadata: dict[str, JsonValue] = Field(description="Дополнительные данные клиента")
    idempotency_key: str = Field(description="Ключ исходного запроса клиента")
    webhook_url: str = Field(description="Нормализованный адрес получателя уведомления")
    processed_at: datetime | None = Field(
        description="Момент получения финального результата шлюза"
    )
    webhook_delivered_at: datetime | None = Field(
        description="Момент подтверждённой доставки webhook"
    )
    last_error: str | None = Field(description="Имя класса последней технической ошибки")


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
