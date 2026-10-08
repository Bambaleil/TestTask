"""Краткий HTTP-ответ о принятом платеже."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from payment_service.modules.payments.domain.constants import PaymentStatus


class PaymentAccepted(BaseModel):
    """Краткий ответ после принятия платежа в обработку."""

    payment_id: UUID = Field(description="Уникальный идентификатор платежа")
    status: PaymentStatus = Field(description="Текущий результат обработки платежа")
    created_at: datetime = Field(description="Момент принятия платежа в UTC")
