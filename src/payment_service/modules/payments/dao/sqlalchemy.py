"""DAO PostgreSQL и преобразование записей в независимые сущности."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.core.errors.exceptions import PersistenceConflictError, RecordNotFoundError
from payment_service.core.events.models import OutboxEvent
from payment_service.core.utils.time import ensure_utc
from payment_service.modules.payments.dao.tables import OutboxRecord, PaymentRecord
from payment_service.modules.payments.domain.constants import Currency, PaymentStatus
from payment_service.modules.payments.domain.entities import Payment


def payment_entity(record: PaymentRecord) -> Payment:
    """Преобразует запись БД в состояние платежа без ORM-инструментации."""
    return Payment(
        id=record.id,
        amount=record.amount,
        currency=Currency(record.currency),
        description=record.description,
        metadata=record.metadata_json,
        status=PaymentStatus(record.status),
        idempotency_key=record.idempotency_key,
        request_hash=record.request_hash,
        webhook_url=record.webhook_url,
        webhook_event_id=record.webhook_event_id,
        created_at=ensure_utc(record.created_at),
        processed_at=ensure_utc(record.processed_at),
        webhook_delivered_at=ensure_utc(record.webhook_delivered_at),
        last_error=record.last_error,
    )


def outbox_entity(record: OutboxRecord) -> OutboxEvent:
    """Преобразует платёжную таблицу Outbox в общий контракт события."""
    return OutboxEvent(
        id=record.id,
        aggregate_id=record.payment_id,
        topic=record.topic,
        payload=record.payload,
        created_at=ensure_utc(record.created_at),
        available_at=ensure_utc(record.available_at),
        published_at=ensure_utc(record.published_at),
        consumed_at=ensure_utc(record.consumed_at),
        publish_attempts=record.publish_attempts,
        last_error=record.last_error,
    )


class PaymentDAO:
    """Реализует порт хранения платежей средствами SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает сессию текущего Unit of Work."""
        self.session = session

    async def get(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        """Получает платёж с необязательной блокировкой строки.

        Args:
            payment_id: UUID платежа.
            for_update: Блокирует строку до commit/rollback при изменении состояния.

        Returns:
            Независимая сущность или None, если запись отсутствует.

        """
        query = select(PaymentRecord).where(PaymentRecord.id == payment_id)
        if for_update:
            query = query.with_for_update()
        record = (await self.session.scalars(query)).one_or_none()
        return None if record is None else payment_entity(record)

    async def get_by_key(self, key: str) -> Payment | None:
        """Возвращает платёж по уникальному ключу исходного запроса."""
        record = (
            await self.session.scalars(
                select(PaymentRecord).where(PaymentRecord.idempotency_key == key)
            )
        ).one_or_none()
        return None if record is None else payment_entity(record)

    async def add(self, payment: Payment) -> None:
        """Добавляет платёж, проверяя ограничения до фиксации транзакции.

        Raises:
            PersistenceConflictError: Запись нарушает ограничение целостности.

        """
        values = asdict(payment)
        values["metadata_json"] = values.pop("metadata")
        self.session.add(PaymentRecord(**values))
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise PersistenceConflictError from error

    async def save(self, payment: Payment) -> None:
        """Сохраняет изменяемое состояние существующего платежа.

        Ключ идемпотентности и исходный запрос не меняются после создания.

        Raises:
            RecordNotFoundError: Запись платежа отсутствует.

        """
        record = await self.session.get(PaymentRecord, payment.id)
        if record is None:
            raise RecordNotFoundError
        record.status = payment.status.value
        record.processed_at = payment.processed_at
        record.webhook_delivered_at = payment.webhook_delivered_at
        record.last_error = payment.last_error


class OutboxDAO:
    """Реализует общий порт Outbox на таблице платёжного модуля."""

    def __init__(self, session: AsyncSession) -> None:
        """Получает ту же сессию, что и DAO платежей."""
        self.session = session

    async def add(self, event: OutboxEvent) -> None:
        """Добавляет событие в транзакцию без независимого commit."""
        values = asdict(event)
        values["payment_id"] = values.pop("aggregate_id")
        self.session.add(OutboxRecord(**values))
        await self.session.flush()

    async def get_for_update(self, event_id: UUID) -> OutboxEvent | None:
        """Возвращает событие с блокировкой для дедупликации попыток."""
        record = (
            await self.session.scalars(
                select(OutboxRecord).where(OutboxRecord.id == event_id).with_for_update()
            )
        ).one_or_none()
        return None if record is None else outbox_entity(record)

    async def get_pending(self, now: datetime, limit: int) -> list[OutboxEvent]:
        """Выбирает готовые события, пропуская строки других диспетчеров.

        Args:
            now: Верхняя граница времени готовности события.
            limit: Максимальное число событий в транзакции публикации.

        Returns:
            События, заблокированные через FOR UPDATE SKIP LOCKED.

        """
        query = (
            select(OutboxRecord)
            .where(OutboxRecord.published_at.is_(None), OutboxRecord.available_at <= now)
            .order_by(OutboxRecord.available_at, OutboxRecord.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [outbox_entity(record) for record in await self.session.scalars(query)]

    async def save(self, event: OutboxEvent) -> None:
        """Сохраняет публикацию, завершение попытки и диагностические поля.

        Raises:
            RecordNotFoundError: Запись события отсутствует.

        """
        record = await self.session.get(OutboxRecord, event.id)
        if record is None:
            raise RecordNotFoundError
        record.available_at = event.available_at
        record.published_at = event.published_at
        record.consumed_at = event.consumed_at
        record.publish_attempts = event.publish_attempts
        record.last_error = event.last_error
