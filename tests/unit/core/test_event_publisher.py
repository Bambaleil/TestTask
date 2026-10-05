from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic

from payment_service.core.events.rabbitmq import RabbitEventPublisher
from payment_service.modules.payments.domain.constants import NEW_TOPIC
from payment_service.modules.payments.handlers.topology import PAYMENT_EXCHANGE


@pytest.mark.parametrize(
    "confirmation", [Basic.Ack(), Basic.Nack(), None], ids=["ack", "nack", "none"]
)
async def test_publish(confirmation: Basic.Ack | Basic.Nack | None) -> None:
    """Принимает только ACK и сохраняет идентификаторы и параметры надёжной доставки."""
    broker = Mock(spec=RabbitBroker)
    broker.publish = AsyncMock(return_value=confirmation)
    publisher = RabbitEventPublisher(broker, {NEW_TOPIC: PAYMENT_EXCHANGE}, 2)
    event_id, payment_id = uuid4(), uuid4()
    payload = {"payment_id": str(payment_id)}
    if isinstance(confirmation, Basic.Ack):
        await publisher.publish(NEW_TOPIC, payload, event_id)
    else:
        with pytest.raises(RuntimeError, match="не подтвердил"):
            await publisher.publish(NEW_TOPIC, payload, event_id)
    broker.publish.assert_awaited_once_with(
        payload,
        exchange=PAYMENT_EXCHANGE,
        routing_key=NEW_TOPIC,
        persist=True,
        mandatory=True,
        timeout=2,
        message_id=str(event_id),
        correlation_id=str(payment_id),
    )


class TestUnknownRoute:
    """Проверки ошибок конфигурации маршрута до передачи события транспорту."""

    async def test_publish(self) -> None:
        """Не отправляет событие брокеру при отсутствии маршрута в конфигурации."""
        broker = Mock(spec=RabbitBroker)
        broker.publish = AsyncMock()
        with pytest.raises(KeyError, match=r"unknown\.topic"):
            await RabbitEventPublisher(broker, {}, 2).publish("unknown.topic", {}, uuid4())
        broker.publish.assert_not_awaited()
