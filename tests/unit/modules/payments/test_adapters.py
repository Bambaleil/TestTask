from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from payment_service.modules.payments.dao.gateway import SimulatedGateway
from payment_service.modules.payments.dao.webhook import HttpWebhookSender
from payment_service.modules.payments.domain.constants import Currency, PaymentStatus
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import WebhookPayload
from payment_service.modules.payments.schemas import PaymentCreate


@pytest.mark.parametrize("status_code", [200, 204, 302, 400, 500])
async def test_send(status_code: int) -> None:
    """Проверяет точную сумму, JSON, ключ дедупликации и отказ на неуспешном HTTP-коде."""
    received: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Записать запрос и вернуть управляемый HTTP-ответ."""
        received.append(request)
        return httpx.Response(status_code)

    payload = WebhookPayload(
        event_id=uuid4(),
        payment_id=uuid4(),
        status=PaymentStatus.SUCCEEDED,
        amount=Decimal("123.45"),
        currency=Currency.RUB,
        metadata={},
        processed_at=datetime.now(UTC),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        sender = HttpWebhookSender(client)
        if status_code >= 300:
            with pytest.raises(httpx.HTTPStatusError):
                await sender.send("https://example.com/webhook", payload)
        else:
            await sender.send("https://example.com/webhook", payload)
    assert received[0].headers["Idempotency-Key"] == str(payload.event_id)
    assert b'"amount":"123.45"' in received[0].content


async def test_charge(payment_data: PaymentCreate) -> None:
    """Проверяет диапазон задержки и стабильность результата при повторном вызове."""
    payment = Payment.create(payment_data.to_command(), "gateway-test")
    gateway = SimulatedGateway()
    with patch(
        "payment_service.modules.payments.dao.gateway.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        first = await gateway.charge(payment)
        second = await gateway.charge(payment)
    assert first == second
    assert first in {PaymentStatus.SUCCEEDED, PaymentStatus.FAILED}
    assert 2 <= sleep.call_args.args[0] <= 5
    assert sleep.await_count == 2
