"""Контракт атомарной операции над репозиториями."""

from types import TracebackType
from typing import Protocol, Self

from payment_service.core.events.contracts import OutboxStore


class UnitOfWork(Protocol):
    """Объединяет изменения в одну транзакцию с явным commit."""

    @property
    def outbox(self) -> OutboxStore:
        """Предоставляет порт Outbox текущей транзакции."""
        ...

    async def __aenter__(self) -> Self:
        """Открывает транзакцию и предоставляет её репозитории."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Откатывает незафиксированные изменения и закрывает ресурсы."""
        ...

    async def commit(self) -> None:
        """Атомарно фиксирует все изменения текущей операции."""
        ...

    async def rollback(self) -> None:
        """Отменяет все незафиксированные изменения."""
        ...


class UnitOfWorkFactory(Protocol):
    """Создаёт независимую транзакцию для каждой прикладной операции."""

    def __call__(self) -> UnitOfWork:
        """Возвращает новый Unit of Work."""
        ...
