"""Фоновая публикация подтверждённых транзакционных событий."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from payment_service.core.db.contracts import UnitOfWorkFactory
from payment_service.core.events.contracts import EventPublisher
from payment_service.core.utils.retry import retry_delay
from payment_service.core.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxOptions:
    """Задаёт параметры фоновой публикации независимо от настроек приложения."""

    batch_size: int = 50
    poll_interval: float = 0.5


class OutboxDispatcher:
    """Публикует готовые события и сохранять состояние после publisher confirm."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, publisher: EventPublisher, options: OutboxOptions
    ) -> None:
        """Получает порты атомарного хранения и подтверждённой публикации.

        Args:
            uow_factory: Создаёт транзакцию с портом Outbox.
            publisher: Ожидает подтверждения от транспорта.
            options: Размер пачки и интервал фонового опроса.
        """
        self.uow_factory = uow_factory
        self.publisher = publisher
        self.options = options

    async def dispatch_batch(self) -> int:
        """Публикует готовую пачку и фиксирует только подтверждённые события.

        Ошибка отдельной публикации сохраняет событие для повторной попытки.
        Сбой commit после подтверждения может привести к повторной публикации.

        Returns:
            Число событий, подтверждённых транспортом и сохранённых в транзакции.

        Raises:
            Exception: Транзакция не смогла сохранить новое состояние Outbox.
        """
        published = 0
        async with self.uow_factory() as uow:
            events = await uow.outbox.get_pending(utcnow(), self.options.batch_size)
            for event in events:
                event.publish_attempts += 1
                try:
                    await self.publisher.publish(event.topic, event.payload, event.id)
                except Exception as error:
                    event.last_error = type(error).__name__
                    event.available_at = utcnow() + timedelta(
                        seconds=min(retry_delay(min(event.publish_attempts, 8), 1), 60)
                    )
                    logger.warning("outbox_publish_failed event_id=%s", event.id)
                else:
                    # Если commit упадёт после confirm, событие будет опубликовано
                    # повторно. Consumer дедуплицирует его по event.id в Outbox.
                    event.published_at = utcnow()
                    event.last_error = None
                    published += 1
                await uow.outbox.save(event)
            await uow.commit()
        return published

    async def run(self) -> None:
        """Опрашивает Outbox до отмены задачи, переживая временные сбои инфраструктуры."""
        while True:
            try:
                await self.dispatch_batch()
            except Exception as error:
                logger.warning("outbox_iteration_failed error=%s", type(error).__name__)
            await asyncio.sleep(self.options.poll_interval)
