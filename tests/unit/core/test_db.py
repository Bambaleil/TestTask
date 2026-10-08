from dataclasses import asdict

import pytest
from sqlalchemy import func, select

from payment_service.core.db.connection import SessionFactory, create_engine
from payment_service.core.db.unit_of_work import SQLAlchemyUnitOfWork
from payment_service.core.errors.exceptions import PersistenceConflictError
from payment_service.modules.payments.dao.tables import PaymentRecord
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate
from tests.fakes import ServiceSettings


async def test_create_engine(settings: ServiceSettings) -> None:
    """Создаёт PostgreSQL-пул с ограничениями размера и без подключения к сети."""
    settings = settings.model_copy(
        update={"database_pool_size": 3, "database_max_overflow": 4, "database_pool_timeout": 2}
    )
    engine = create_engine(settings)
    try:
        assert engine.url.render_as_string(hide_password=False) == (
            settings.database_url.get_secret_value()
        )
        assert engine.pool.size() == 3
        assert engine.pool.timeout() == 2
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


async def test_commit(sessions: SessionFactory, payment_data: PaymentCreate) -> None:
    """Преобразует нарушение уникальности при commit и откатывает вторую запись."""
    repository = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    original = await repository.create(payment_data.to_command(), "duplicate-commit")
    duplicate = Payment.create(payment_data.to_command(), original.idempotency_key)
    values = asdict(duplicate)
    values["metadata_json"] = values.pop("metadata")
    with pytest.raises(PersistenceConflictError) as error:
        async with SQLAlchemyUnitOfWork(sessions) as uow:
            uow.session.add(PaymentRecord(**values))
            await uow.commit()
    assert error.value.__cause__ is not None
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(PaymentRecord)) == 1
    assert (await repository.get(original.id)).id == original.id
