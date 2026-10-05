"""Сборка платёжного модуля и регистрация его внешних контрактов."""

from dataclasses import dataclass

from fastapi import Depends, FastAPI

from payment_service.core.auth.dependencies import require_api_key
from payment_service.core.errors.handlers import ErrorResponse, install_error_handlers
from payment_service.modules.payments.domain.contracts import (
    PaymentGateway,
    PaymentUnitOfWorkFactory,
    WebhookSender,
)
from payment_service.modules.payments.domain.exceptions import (
    IdempotencyConflictError,
    PaymentNotFoundError,
)
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.views import router


@dataclass(frozen=True)
class PaymentModule:
    """Объединяет repository и обработчик домена с внедрёнными адаптерами."""

    repository: PaymentRepository
    processor: PaymentProcessor

    @classmethod
    def build(
        cls,
        uow_factory: PaymentUnitOfWorkFactory,
        gateway: PaymentGateway,
        webhooks: WebhookSender,
        retry_base_delay: float,
    ) -> "PaymentModule":
        """Собирает модуль без создания SQL-, HTTP- или брокерных подключений.

        Args:
            uow_factory: Порт атомарного хранения платежа и Outbox.
            gateway: Реальный или тестовый платёжный провайдер.
            webhooks: Реальный или тестовый получатель уведомлений.
            retry_base_delay: Задержка после первой неуспешной попытки.

        Returns:
            Модуль с согласованными бизнес-операциями и обработчиком.

        """
        return cls(
            repository=PaymentRepository(uow_factory),
            processor=PaymentProcessor(uow_factory, gateway, webhooks, retry_base_delay),
        )


def register_http(app: FastAPI, repository: PaymentRepository | None = None) -> None:
    """Подключает API и публичные ошибки платёжного модуля к приложению."""
    if repository is not None:
        app.state.payment_repository = repository
    app.include_router(router, dependencies=[Depends(require_api_key)])
    install_error_handlers(
        app,
        {
            PaymentNotFoundError: ErrorResponse(404, "Платёж не найден"),
            IdempotencyConflictError: ErrorResponse(
                409, "Ключ идемпотентности уже использован для другого запроса"
            ),
        },
    )
