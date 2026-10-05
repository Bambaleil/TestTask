"""Общий RabbitMQ-адаптер без знания платёжных маршрутов."""

from collections.abc import Mapping
from uuid import UUID

from faststream.rabbit import Channel, RabbitBroker, RabbitExchange
from pamqp.commands import Basic

from payment_service.core.contracts import JsonValue
from payment_service.core.settings import WorkerSettings


def create_broker(settings: WorkerSettings) -> RabbitBroker:
    """Создаёт брокер с publisher confirms и одним сообщением в обработке."""
    return RabbitBroker(
        settings.rabbitmq_url.get_secret_value(),
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
        graceful_timeout=30,
        logger=None,
    )


class RabbitEventPublisher:
    """Публикует persistent-события и ждать положительного подтверждения."""

    def __init__(
        self, broker: RabbitBroker, routes: Mapping[str, RabbitExchange], timeout: float
    ) -> None:
        """Получает подключённый брокер и доменную таблицу маршрутов.

        Args:
            broker: Общий брокер с включёнными publisher confirms.
            routes: Соответствие topic → exchange, задаваемое модулем.
            timeout: Таймаут подтверждения в секундах.
        """
        self.broker = broker
        self.routes = routes
        self.timeout = timeout

    async def publish(self, topic: str, payload: dict[str, JsonValue], event_id: UUID) -> None:
        """Публикует persistent-сообщение и проверяет положительное подтверждение.

        Args:
            topic: Зарегистрированный маршрут события.
            payload: JSON-совместимое тело сообщения.
            event_id: Стабильный message_id для повторной публикации.

        Raises:
            KeyError: В таблице маршрутов нет topic.
            RuntimeError: Брокер вернул отрицательное или пустое подтверждение.
            Exception: Публикация не прошла проверку маршрута или истёк таймаут.
        """
        exchange = self.routes[topic]
        confirmation = await self.broker.publish(
            payload,
            exchange=exchange,
            routing_key=topic,
            persist=True,
            mandatory=True,
            timeout=self.timeout,
            message_id=str(event_id),
            correlation_id=str(payload.get("payment_id", "")),
        )
        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("Брокер не подтвердил публикацию события")
