"""Независимая от БД модель транзакционного события."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from payment_service.core.contracts import JsonValue
from payment_service.core.utils.time import utcnow


@dataclass(kw_only=True)
class OutboxEvent:
    """Хранит событие любого агрегата и состояние публикации/обработки.

    Attributes:
        aggregate_id: Идентификатор сущности, к которой относится событие.
        topic: Маршрут, определяемый доменным модулем.
        available_at: Момент, раньше которого публикация запрещена.
        consumed_at: Долговечная отметка завершённой прикладной попытки.

    """

    aggregate_id: UUID
    topic: str
    payload: dict[str, JsonValue]
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utcnow)
    available_at: datetime = field(default_factory=utcnow)
    published_at: datetime | None = None
    consumed_at: datetime | None = None
    publish_attempts: int = 0
    last_error: str | None = None
