"""Входная схема HTTP-запроса создания платежа."""

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue

from payment_service.modules.payments.domain.constants import Currency
from payment_service.modules.payments.domain.entities import CreatePaymentCommand
from payment_service.modules.payments.schemas.types import Money


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
