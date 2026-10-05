"""Валюты, состояния и события предметной области платежей."""

from enum import StrEnum

MAX_ATTEMPTS = 3
NEW_TOPIC = "payments.new"
DEAD_TOPIC = "payments.dead"


class Currency(StrEnum):
    """Описывает поддерживаемые валюты платежа."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    """Описывает состояния обработки платежа."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
