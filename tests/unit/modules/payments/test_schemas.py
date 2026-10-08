from decimal import Decimal

import pytest
from pydantic import ValidationError

from payment_service.core.utils.retry import retry_delay
from payment_service.modules.payments.schemas import PaymentCreate


@pytest.mark.parametrize("amount", ["123.450", "123.45"])
def test_fingerprint(payment_data: PaymentCreate, amount: str) -> None:
    """Проверяет нормализацию суммы и порядок ключей JSON."""
    modified = payment_data.model_copy(
        update={"amount": Decimal(amount), "metadata": {"z": 1, "a": 2}}
    )
    reference = payment_data.model_copy(update={"metadata": {"a": 2, "z": 1}})
    assert modified.fingerprint() == reference.fingerprint()
    assert payment_data.fingerprint() != reference.fingerprint()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0"),
        ("amount", "-1"),
        ("amount", "1.001"),
        ("amount", "10000000000000000"),
        ("amount", "NaN"),
        ("currency", "GBP"),
        ("description", ""),
        ("webhook_url", "ftp://example.com"),
        ("webhook_url", "not-a-url"),
        ("unknown", "extra"),
        ("metadata", {"bad": float("nan")}),
        ("metadata", {"nested": [float("inf")]}),
    ],
)
def test_model_validate(payment_data: PaymentCreate, field: str, value: object) -> None:
    """Отклонить некорректные суммы, валюты и URL на границе API."""
    body = payment_data.model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(body)


@pytest.mark.parametrize(("attempt", "expected"), [(1, 2), (2, 4), (3, 8)])
def test_retry_delay(attempt: int, expected: float) -> None:
    """Проверяет экспоненциальное увеличение задержки."""
    assert retry_delay(attempt, 2) == expected
