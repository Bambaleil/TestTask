"""Ошибки предметной области платежей."""

from payment_service.core.errors.exceptions import BusinessError


class PaymentNotFoundError(BusinessError):
    """Запрошенный платёж отсутствует в хранилище."""


class IdempotencyConflictError(BusinessError):
    """Один ключ идемпотентности использован для разных запросов."""


class InvalidEventError(BusinessError):
    """Событие не соответствует сохранённой записи или платёж отсутствует."""
