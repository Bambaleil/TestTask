from uuid import uuid4

import pytest

from payment_service.core.db.connection import SessionFactory
from payment_service.core.errors.exceptions import RecordNotFoundError
from payment_service.modules.payments.dao.models import PaymentCreate
from payment_service.modules.payments.dao.sqlalchemy import OutboxDAO, PaymentDAO
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import new_payment_event


class TestMissingPayment:
    """Проверки сохранения платежа после удаления записи из хранилища."""

    async def test_save(self, sessions: SessionFactory, payment_data: PaymentCreate) -> None:
        """Сообщает об отсутствующей записи и не вставляет платёж вместо обновления."""
        async with sessions() as session:
            with pytest.raises(RecordNotFoundError):
                await PaymentDAO(session).save(Payment.create(payment_data.to_command(), "missing"))
            assert await PaymentDAO(session).get_by_key("missing") is None


class TestMissingOutboxEvent:
    """Проверки сохранения состояния отсутствующего события."""

    async def test_save(self, sessions: SessionFactory) -> None:
        """Сообщает об отсутствии события, не создавая новую запись Outbox."""
        event = new_payment_event(uuid4())
        async with sessions() as session:
            with pytest.raises(RecordNotFoundError):
                await OutboxDAO(session).save(event)
            assert await OutboxDAO(session).get_for_update(event.id) is None
