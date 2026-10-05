"""Детерминированные реализации внешних портов для тестов."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Self
from uuid import UUID

from payment_service.core.contracts import JsonValue
from payment_service.core.errors.exceptions import PersistenceConflictError
from payment_service.core.events.models import OutboxEvent
from payment_service.core.settings import ApiSettings, WorkerSettings
from payment_service.modules.payments.domain.constants import PaymentStatus
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import WebhookPayload


class FakeGateway:
    """Шлюз с известным результатом и счётчиком обращений."""

    def __init__(self, outcome: PaymentStatus = PaymentStatus.SUCCEEDED, failures: int = 0) -> None:
        """Задать результат и количество временных сбоев."""
        self.outcome = outcome
        self.failures = failures
        self.calls = 0

    async def charge(self, payment: Payment) -> PaymentStatus:
        """Эмулировать результат без реальной задержки."""
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError
        return self.outcome


class FakeWebhooks:
    """Получатель webhook с управляемыми ошибками."""

    def __init__(self, failures: int = 0) -> None:
        """Задать число неуспешных HTTP-попыток."""
        self.failures = failures
        self.calls: list[WebhookPayload] = []

    async def send(self, url: str, payload: WebhookPayload) -> None:
        """Записать уведомление и при необходимости выбросить ошибку."""
        self.calls.append(payload)
        if len(self.calls) <= self.failures:
            raise TimeoutError


class FakePublisher:
    """Издатель для проверки подтверждений и повторной публикации."""

    def __init__(self, failures: int = 0) -> None:
        """Задать число сбоев до подтверждённой публикации."""
        self.failures = failures
        self.calls: list[tuple[str, dict[str, JsonValue], UUID]] = []

    async def publish(self, topic: str, payload: dict[str, JsonValue], event_id: UUID) -> None:
        """Записать публикацию и эмулировать ошибку подтверждения."""
        self.calls.append((topic, payload, event_id))
        if len(self.calls) <= self.failures:
            raise ConnectionError


@dataclass
class MemoryState:
    """Хранит копируемое состояние тестового Unit of Work."""

    payments: dict[UUID, Payment] = field(default_factory=dict)
    events: dict[UUID, OutboxEvent] = field(default_factory=dict)


class MemoryPaymentStore:
    """Реализует платёжный порт без ORM и неявного отслеживания изменений."""

    def __init__(self, state: MemoryState) -> None:
        """Получает рабочий снимок текущей транзакции."""
        self.state = state

    async def get(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        """Возвращает отдельную копию состояния платежа."""
        return deepcopy(self.state.payments.get(payment_id))

    async def get_by_key(self, key: str) -> Payment | None:
        """Находит платёж по исходному клиентскому ключу."""
        return next(
            (
                deepcopy(payment)
                for payment in self.state.payments.values()
                if payment.idempotency_key == key
            ),
            None,
        )

    async def add(self, payment: Payment) -> None:
        """Добавляет платёж, соблюдая уникальность ключа."""
        if await self.get_by_key(payment.idempotency_key) is not None:
            raise PersistenceConflictError
        self.state.payments[payment.id] = deepcopy(payment)

    async def save(self, payment: Payment) -> None:
        """Сохраняет только явно переданное новое состояние."""
        self.state.payments[payment.id] = deepcopy(payment)


class MemoryOutboxStore:
    """Реализует порт Outbox и управляемый сбой атомарной записи."""

    def __init__(self, state: MemoryState, fail_write: bool = False) -> None:
        """Получает снимок транзакции и сценарий ошибки записи события."""
        self.state = state
        self.fail_write = fail_write

    async def add(self, event: OutboxEvent) -> None:
        """Записывает событие или имитирует ошибку долговечного хранения."""
        if self.fail_write:
            raise RuntimeError("Не удалось записать событие")
        self.state.events[event.id] = deepcopy(event)

    async def save(self, event: OutboxEvent) -> None:
        """Сохраняет явно изменённое состояние события."""
        self.state.events[event.id] = deepcopy(event)

    async def get_for_update(self, event_id: UUID) -> OutboxEvent | None:
        """Возвращает независимую копию события в последовательном тесте."""
        return deepcopy(self.state.events.get(event_id))

    async def get_pending(self, now: datetime, limit: int) -> list[OutboxEvent]:
        """Возвращает готовые события без имитации PostgreSQL-блокировок."""
        return [
            deepcopy(event)
            for event in self.state.events.values()
            if event.published_at is None and event.available_at <= now
        ][:limit]


class MemoryUnitOfWork:
    """Применяет копию состояния только при явном commit."""

    def __init__(self, factory: "MemoryUnitOfWorkFactory") -> None:
        """Создаёт изолированный снимок без изменения общего состояния."""
        self.factory = factory
        self.state = deepcopy(factory.state)
        self.payments = MemoryPaymentStore(self.state)
        self.outbox = MemoryOutboxStore(self.state, factory.fail_event_write)

    async def __aenter__(self) -> Self:
        """Предоставляет тестовые порты текущей операции."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Оставляет общую копию без изменений при выходе без commit."""
        await self.rollback()

    async def commit(self) -> None:
        """Атомарно заменяет общее состояние рабочим снимком."""
        self.factory.state = deepcopy(self.state)

    async def rollback(self) -> None:
        """Отбрасывает незафиксированный рабочий снимок."""
        self.state = deepcopy(self.factory.state)


class MemoryUnitOfWorkFactory:
    """Предоставляет независимые транзакции для чистых бизнес-тестов."""

    def __init__(self, *, fail_event_write: bool = False) -> None:
        """Создаёт пустое хранилище и сценарий сбоя записи Outbox."""
        self.state = MemoryState()
        self.fail_event_write = fail_event_write

    def __call__(self) -> MemoryUnitOfWork:
        """Возвращает новую транзакцию над текущим состоянием."""
        return MemoryUnitOfWork(self)


class ServiceSettings(ApiSettings, WorkerSettings):
    """Объединяет настройки процессов только для общих тестовых фикстур."""
