from unittest.mock import AsyncMock, Mock, patch

import pytest
from faststream.rabbit.message import RabbitMessage
from sqlalchemy import select

from payment_service.core.db.connection import SessionFactory
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.exceptions import InvalidEventError
from payment_service.modules.payments.handlers.rabbitmq import PaymentMessageHandler, decode_event
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from tests.fakes import FakeGateway, FakeWebhooks


@pytest.mark.parametrize("failure", [None, TimeoutError, InvalidEventError])
async def test_process_payment(
    sessions: SessionFactory, payment_data: PaymentCreate, failure: type[Exception] | None
) -> None:
    """Проверяет ACK после успеха, NACK при сбое БД и reject чужого события."""
    await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
        payment_data.to_command(), "ack-test"
    )
    async with sessions() as session:
        event = (await session.scalars(select(OutboxEvent))).one()
    processor = PaymentProcessor(
        PaymentUnitOfWorkFactory(sessions), FakeGateway(), FakeWebhooks(), 2
    )
    message = Mock(spec=RabbitMessage)
    message.message_id = "unit-test"
    message.ack = AsyncMock()
    message.nack = AsyncMock()
    message.reject = AsyncMock()
    handler = PaymentMessageHandler(processor, 2)
    with patch.object(processor, "process", new=AsyncMock(side_effect=failure)):
        with patch(
            "payment_service.modules.payments.handlers.rabbitmq.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await handler.process_payment(event.payload, message)
    assert message.ack.await_count == int(failure is None)
    assert message.nack.await_count == int(failure is TimeoutError)
    assert message.reject.await_count == int(failure is InvalidEventError)
    if failure is TimeoutError:
        message.nack.assert_awaited_once_with(requeue=True)
    if failure is InvalidEventError:
        message.reject.assert_awaited_once_with(requeue=False)


class TestMalformedMessage:
    """Проверки ошибочных сообщений без обращения к прикладной обработке."""

    @pytest.mark.parametrize("body", [None, [], "garbage", {"payment_id": "bad"}])
    async def test_process_payment(self, sessions: SessionFactory, body: object) -> None:
        """Отправляет в DLQ событие, которое не прошло валидацию Pydantic."""
        processor = PaymentProcessor(
            PaymentUnitOfWorkFactory(sessions), FakeGateway(), FakeWebhooks(), 2
        )
        message = Mock(spec=RabbitMessage)
        message.message_id = "unit-test"
        message.reject = AsyncMock()
        handler = PaymentMessageHandler(processor, 2)
        await handler.process_payment(body, message)
        message.reject.assert_awaited_once_with(requeue=False)


@pytest.mark.parametrize("body", [b"broken-json", b"\xff", b'{"attempt": 1}', b"[]"])
def test_decode_event(body: bytes) -> None:
    """Не допустить зависания невалидного JSON до входа в ручной ACK-обработчик."""
    message = Mock(spec=RabbitMessage)
    message.body = body
    decoded = decode_event(message)
    if body == b'{"attempt": 1}':
        assert decoded == {"attempt": 1}
    elif body == b"[]":
        assert decoded == []
    else:
        assert decoded is None
