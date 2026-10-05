"""Топология сообщений платёжного модуля."""

from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue

from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC

PAYMENT_EXCHANGE = RabbitExchange("payments", durable=True)
DEAD_EXCHANGE = RabbitExchange("payments.dlx", durable=True)
PAYMENT_QUEUE = RabbitQueue(
    NEW_TOPIC,
    durable=True,
    routing_key=NEW_TOPIC,
    arguments={
        "x-dead-letter-exchange": DEAD_EXCHANGE.name,
        "x-dead-letter-routing-key": DEAD_TOPIC,
    },
)
DEAD_QUEUE = RabbitQueue(DEAD_TOPIC, durable=True, routing_key=DEAD_TOPIC)


async def declare_topology(broker: RabbitBroker) -> None:
    """Объявляет очереди и связи до первой публикации и запуска consumer."""
    payment_exchange = await broker.declare_exchange(PAYMENT_EXCHANGE)
    dead_exchange = await broker.declare_exchange(DEAD_EXCHANGE)
    dead_queue = await broker.declare_queue(DEAD_QUEUE)
    await dead_queue.bind(dead_exchange, routing_key=DEAD_TOPIC)
    payment_queue = await broker.declare_queue(PAYMENT_QUEUE)
    await payment_queue.bind(payment_exchange, routing_key=NEW_TOPIC)
