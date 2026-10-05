"""Реализация границ транзакций SQLAlchemy."""

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError

from payment_service.core.db.connection import SessionFactory
from payment_service.core.errors.exceptions import PersistenceConflictError


class SQLAlchemyUnitOfWork:
    """Управляет сессией; состав DAO определяется доменным модулем.

    Изменения сохраняются только явным commit. Выход из контекста всегда
    освобождает сессию, включая ошибки и отмену асинхронной задачи.
    """

    def __init__(self, sessions: SessionFactory) -> None:
        """Создаёт новую сессию без преждевременного подключения к БД."""
        self.session = sessions()

    async def __aenter__(self) -> Self:
        """Открывает транзакцию для DAO текущей операции."""
        await self.session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Откатывает незавершённую транзакцию и освобождает сессию."""
        try:
            await self.rollback()
        finally:
            await self.session.close()

    async def commit(self) -> None:
        """Фиксирует изменения и переводит конфликт БД в общий контракт ошибки.

        Raises:
            PersistenceConflictError: Нарушено ограничение целостности.

        """
        try:
            await self.session.commit()
        except IntegrityError as error:
            raise PersistenceConflictError from error

    async def rollback(self) -> None:
        """Отменяет оставшиеся изменения после ошибки или операции чтения."""
        await self.session.rollback()
