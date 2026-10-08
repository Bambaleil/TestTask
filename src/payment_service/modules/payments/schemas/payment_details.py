"""Подробный HTTP-ответ о состоянии платежа."""

from datetime import datetime
from decimal import Decimal

from pydantic import Field, JsonValue

from payment_service.modules.payments.domain.constants import Currency
from payment_service.modules.payments.schemas.payment_accepted import PaymentAccepted


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
