"""Подключение платёжных DAO к общей транзакции SQLAlchemy."""

from payment_service.core.db.connection import SessionFactory
from payment_service.core.db.unit_of_work import SQLAlchemyUnitOfWork
from payment_service.modules.payments.dao.sqlalchemy import OutboxDAO, PaymentDAO


class PaymentUnitOfWork(SQLAlchemyUnitOfWork):
    """Предоставляет DAO платежей и Outbox, связанные одной сессией."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Создаёт атомарную операцию над таблицами платежного модуля."""
        super().__init__(sessions)
        self.payments = PaymentDAO(self.session)
        self.outbox = OutboxDAO(self.session)


class PaymentUnitOfWorkFactory:
    """Создаёт новый экземпляр Unit of Work для каждой операции."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Сохраняет фабрику сессий, общую для модуля."""
        self.sessions = sessions

    def __call__(self) -> PaymentUnitOfWork:
        """Возвращает независимую транзакцию с платёжными DAO."""
        return PaymentUnitOfWork(self.sessions)
