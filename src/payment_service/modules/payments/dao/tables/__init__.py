"""Регистрация ORM-сущностей платежного модуля в общей metadata."""

from payment_service.modules.payments.dao.tables.outbox_record import OutboxRecord
from payment_service.modules.payments.dao.tables.payment_record import PaymentRecord

__all__ = ["OutboxRecord", "PaymentRecord"]
