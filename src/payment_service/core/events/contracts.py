"""Порты хранилища Outbox и подтверждённой публикации событий."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from payment_service.core.contracts import JsonValue
from payment_service.core.events.models import OutboxEvent


class EventPublisher(Protocol):
    """Публикует события с подтверждением транспортом."""

    async def publish(self, topic: str, payload: dict[str, JsonValue], event_id: UUID) -> None:
        """Ожидает положительного подтверждения доставки.

        Args:
            topic: Маршрут события.
            payload: JSON-совместимое тело сообщения.
            event_id: Стабильный идентификатор для повторной публикации.

        Raises:
            Exception: Транспорт не подтвердил публикацию.

        """
        ...


class OutboxStore(Protocol):
    """Определяет операции хранения, нужные диспетчеру и обработчику событий."""

    async def add(self, event: OutboxEvent) -> None:
        """Добавляет событие в текущую транзакцию."""
        ...

    async def save(self, event: OutboxEvent) -> None:
        """Сохраняет изменения заблокированного события."""
        ...

    async def get_for_update(self, event_id: UUID) -> OutboxEvent | None:
        """Возвращает событие с блокировкой до завершения транзакции."""
        ...

    async def get_pending(self, now: datetime, limit: int) -> list[OutboxEvent]:
        """Возвращает готовые события, пропуская блокировки других издателей."""
        ...
