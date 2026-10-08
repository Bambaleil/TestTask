"""Ожидание наблюдаемого состояния настоящего RabbitMQ с ограниченным таймаутом."""

import asyncio

from aio_pika import IncomingMessage
from faststream.rabbit import RabbitBroker

from payment_service.modules.payments.handlers import topology as messaging


async def receive_dead_message(broker: RabbitBroker) -> IncomingMessage:
    """Возвращает сообщение из тестовой DLQ или завершает ожидание по таймауту."""
    queue = await broker.declare_queue(messaging.DEAD_QUEUE)
    async with asyncio.timeout(10):
        while True:
            message = await queue.get(fail=False)
            if message is not None:
                return message
            await asyncio.sleep(0.02)
