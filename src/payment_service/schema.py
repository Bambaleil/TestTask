"""Регистрация ORM-таблиц подключённых модулей для миграций."""

from sqlalchemy import MetaData

from payment_service.modules.payments.dao.tables import PaymentRecord


def get_metadata() -> MetaData:
    """Возвращает общую схему с таблицами подключённого платёжного модуля."""
    return PaymentRecord.metadata
