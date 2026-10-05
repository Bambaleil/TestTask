"""Сущности платежа и команды, независимые от ORM и HTTP."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from payment_service.core.contracts import JsonValue
from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.domain.constants import Currency, PaymentStatus


@dataclass(kw_only=True, frozen=True)
class CreatePaymentCommand:
    """Передаёт валидированные данные создания платежа в бизнес-логику."""

    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, JsonValue]
    webhook_url: str

    def fingerprint(self) -> str:
        """Возвращает отпечаток нормализованного тела запроса.

        Суммы 10, 10.0 и 10.00 равнозначны. Порядок ключей JSON не влияет
        на сравнение; другие изменения тела означают другой запрос.

        Returns:
            SHA-256 отпечаток без ключа идемпотентности.

        """
        body = {
            "amount": format(self.amount.quantize(Decimal("0.01")), "f"),
            "currency": self.currency.value,
            "description": self.description,
            "metadata": self.metadata,
            "webhook_url": self.webhook_url,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(kw_only=True)
class Payment:
    """Хранит состояние платежа без сведений о способе его сохранения.

    Attributes:
        request_hash: Отпечаток исходного запроса для защиты от конфликтов.
        webhook_event_id: Один идентификатор уведомления для всех его повторов.
        webhook_delivered_at: Момент подтверждённой доставки уведомления.

    """

    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, JsonValue]
    idempotency_key: str
    request_hash: str
    webhook_url: str
    id: UUID = field(default_factory=uuid4)
    webhook_event_id: UUID = field(default_factory=uuid4)
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = field(default_factory=utcnow)
    processed_at: datetime | None = None
    webhook_delivered_at: datetime | None = None
    last_error: str | None = None

    @classmethod
    def create(cls, command: CreatePaymentCommand, key: str) -> "Payment":
        """Создаёт новый платёж из команды клиента.

        Args:
            command: Нормализованные данные запроса.
            key: Уникальный ключ, предоставленный клиентом.

        Returns:
            Платёж в состоянии pending с собственными UUID.

        """
        return cls(
            amount=command.amount,
            currency=command.currency,
            description=command.description,
            metadata=command.metadata,
            idempotency_key=key,
            request_hash=command.fingerprint(),
            webhook_url=command.webhook_url,
        )
