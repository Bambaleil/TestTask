"""HTTP API платёжного модуля; бизнес-правила находятся в repository."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from payment_service.modules.payments.dao.models import (
    PaymentAccepted,
    PaymentCreate,
    PaymentDetails,
)
from payment_service.modules.payments.dependencies import get_payment_repository
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.repository import PaymentRepository

router = APIRouter(prefix="/api/v1/payments", tags=["Платежи"])


def payment_details(payment: Payment) -> PaymentDetails:
    """Преобразует состояние платежа в публичный ответ API."""
    return PaymentDetails(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        processed_at=payment.processed_at,
        webhook_delivered_at=payment.webhook_delivered_at,
        last_error=payment.last_error,
    )


@router.post(
    "",
    response_model=PaymentAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    description="Создаёт платёж и возвращает идентификатор принятой операции.",
    responses={401: {"description": "Неверный API-ключ"}, 409: {"description": "Конфликт ключа"}},
)
async def create_payment(
    data: PaymentCreate,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"^\S+$")
    ],
    repository: Annotated[PaymentRepository, Depends(get_payment_repository)],
) -> PaymentAccepted:
    """Создаёт платёж и возвращает идентификатор принятой операции.

    - *Rights*: действительный X-API-Key.
    - *Idempotency*: одинаковый ключ и тело возвращают тот же платёж.

    Args:
        data: Сумма, валюта, описание, метаданные и адрес уведомления.
        idempotency_key: Обязательный ключ исходного клиентского запроса.
        repository: Бизнес-операции платёжного модуля.

    Returns:
        Идентификатор, текущий статус и дата создания платежа; HTTP 202.

    Raises:
        IdempotencyConflictError: Ключ использован с другим телом; HTTP 409.

    """
    payment = await repository.create(data.to_command(), idempotency_key)
    return PaymentAccepted(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetails,
    description="Возвращает сведения о платеже и результате его обработки.",
    responses={401: {"description": "Неверный API-ключ"}, 404: {"description": "Платёж не найден"}},
)
async def get_payment(
    payment_id: UUID,
    repository: Annotated[PaymentRepository, Depends(get_payment_repository)],
) -> PaymentDetails:
    """Возвращает сведения о платеже и результате его обработки.

    - *Rights*: действительный X-API-Key.

    Args:
        payment_id: Идентификатор, полученный при создании платежа.
        repository: Бизнес-операции платёжного модуля.

    Returns:
        Данные платежа, его статус и сведения о доставке webhook.

    Raises:
        PaymentNotFoundError: Платёж отсутствует; HTTP 404.

    """
    return payment_details(await repository.get(payment_id))
