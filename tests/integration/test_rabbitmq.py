import asyncio
import json
from contextlib import suppress
from uuid import uuid4

import pytest
from aio_pika import IncomingMessage
from faststream import AckPolicy
from faststream.rabbit import RabbitBroker
from sqlalchemy import select

from payment_service.core.db.connection import SessionFactory
from payment_service.core.events.outbox import OutboxDispatcher, OutboxOptions
from payment_service.core.events.rabbitmq import RabbitEventPublisher
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.tables import OutboxRecord as OutboxEvent
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC
from payment_service.modules.payments.handlers import topology as messaging
from payment_service.modules.payments.handlers.rabbitmq import PaymentMessageHandler, decode_event
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from tests.fakes import FakeGateway, FakeWebhooks, ServiceSettings

pytestmark = pytest.mark.integration


async def receive_dead_message(broker: RabbitBroker) -> IncomingMessage:
    """Дождаться сообщения из изолированной DLQ с ограниченным таймаутом."""
    queue = await broker.declare_queue(messaging.DEAD_QUEUE)
    async with asyncio.timeout(10):
        while True:
            message = await queue.get(fail=False)
            if message is not None:
                return message
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("webhook_failures", [0, 1, 3])
async def test_process_payment(
    sessions: SessionFactory,
    payment_data: PaymentCreate,
    settings: ServiceSettings,
    rabbit_broker: RabbitBroker,
    webhook_failures: int,
) -> None:
    """Проверяет настоящий цикл PostgreSQL → Outbox → RabbitMQ → consumer → retry/DLQ."""
    payment = await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).create(
        payment_data.to_command(), "rabbit-test"
    )
    gateway = FakeGateway()
    webhooks = FakeWebhooks(webhook_failures)
    processor = PaymentProcessor(
        PaymentUnitOfWorkFactory(sessions), gateway, webhooks, retry_base_delay=0.05
    )
    handler = PaymentMessageHandler(processor, 0.05)
    rabbit_broker.subscriber(
        messaging.PAYMENT_QUEUE,
        messaging.PAYMENT_EXCHANGE,
        ack_policy=AckPolicy.MANUAL,
        decoder=decode_event,
    )(handler.process_payment)
    await rabbit_broker.start()
    settings = settings.model_copy(update={"outbox_poll_interval": 0.02})
    dispatcher = OutboxDispatcher(
        PaymentUnitOfWorkFactory(sessions),
        RabbitEventPublisher(
            rabbit_broker,
            {NEW_TOPIC: messaging.PAYMENT_EXCHANGE, DEAD_TOPIC: messaging.DEAD_EXCHANGE},
            2,
        ),
        OutboxOptions(poll_interval=0.02),
    )
    task = asyncio.create_task(dispatcher.run())
    try:
        if webhook_failures == 3:
            dead_message = await receive_dead_message(rabbit_broker)
            payload = json.loads(dead_message.body)
            assert payload["payment_id"] == str(payment.id)
            assert payload["attempt"] == 3
            assert payload["status"] == "succeeded"
            await dead_message.ack()
        else:
            async with asyncio.timeout(10):
                # Здесь ожидаем состояние внешней БД, а не событие в памяти процесса.
                while (  # noqa: ASYNC110
                    await PaymentRepository(PaymentUnitOfWorkFactory(sessions)).get(payment.id)
                ).webhook_delivered_at is None:
                    await asyncio.sleep(0.02)
        async with sessions() as session:
            initial = await session.scalar(
                select(OutboxEvent)
                .where(OutboxEvent.topic == NEW_TOPIC)
                .order_by(OutboxEvent.created_at)
            )
            assert initial is not None
        await rabbit_broker.publish(
            initial.payload,
            exchange=messaging.PAYMENT_EXCHANGE,
            routing_key=NEW_TOPIC,
            persist=True,
        )
        # Даём реальному consumer принять дубликат после предыдущего ACK.
        await asyncio.sleep(0.1)
        assert gateway.calls == 1
        assert len(webhooks.calls) == min(webhook_failures + 1, 3)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.parametrize("body", [b"broken-json", None, [], {"payment_id": "bad-id"}])
async def test_decode_event(
    sessions: SessionFactory, rabbit_broker: RabbitBroker, body: object
) -> None:
    """Настоящий RabbitMQ отправляет повреждённое событие в DLQ через reject."""
    handler = PaymentMessageHandler(
        PaymentProcessor(PaymentUnitOfWorkFactory(sessions), FakeGateway(), FakeWebhooks(), 0.05),
        0.05,
    )
    rabbit_broker.subscriber(
        messaging.PAYMENT_QUEUE,
        messaging.PAYMENT_EXCHANGE,
        ack_policy=AckPolicy.MANUAL,
        decoder=decode_event,
    )(handler.process_payment)
    await rabbit_broker.start()
    await rabbit_broker.publish(
        body,
        exchange=messaging.PAYMENT_EXCHANGE,
        routing_key=NEW_TOPIC,
        persist=True,
        message_id=str(uuid4()),
    )
    dead_message = await receive_dead_message(rabbit_broker)
    assert dead_message.headers["x-death"][0]["reason"] == "rejected"
    await dead_message.ack()


async def test_publish(rabbit_broker: RabbitBroker) -> None:
    """Не считать публикацию подтверждённой, если маршрут не связан ни с одной очередью."""
    publisher = RabbitEventPublisher(
        rabbit_broker,
        {NEW_TOPIC: messaging.PAYMENT_EXCHANGE, DEAD_TOPIC: messaging.DEAD_EXCHANGE},
        2,
    )
    with pytest.raises(Exception, match="NO_ROUTE"):
        publisher.routes = {**publisher.routes, "missing.route": messaging.PAYMENT_EXCHANGE}
        await publisher.publish("missing.route", {"payment_id": str(uuid4())}, uuid4())
    # Прямой путь DLQ тоже получает publisher confirm.
    await publisher.publish(DEAD_TOPIC, {"payment_id": str(uuid4())}, uuid4())
    message = await receive_dead_message(rabbit_broker)
    await message.ack()
