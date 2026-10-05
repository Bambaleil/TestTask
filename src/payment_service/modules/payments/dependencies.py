"""Зависимости HTTP-адаптера платёжного модуля."""

from fastapi import Request

from payment_service.modules.payments.repository import PaymentRepository


def get_payment_repository(request: Request) -> PaymentRepository:
    """Возвращает repository, созданный при сборке приложения."""
    repository: PaymentRepository = request.app.state.payment_repository
    return repository
