"""Бизнес-операции платежного модуля: создание и чтение платежей."""

from uuid import UUID

from payment_service.core.errors.exceptions import PersistenceConflictError
from payment_service.modules.payments.domain.contracts import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.entities import CreatePaymentCommand, Payment
from payment_service.modules.payments.domain.events import new_payment_event
from payment_service.modules.payments.domain.exceptions import (
    IdempotencyConflictError,
    PaymentNotFoundError,
)


class PaymentRepository:
    """Оркестрирует операции над портами хранения и Unit of Work.

    Repository содержит бизнес-правила платёжного модуля. Доступ к SQL, HTTP
    и схемам транспорта реализован адаптерами; сюда они не импортируются.
    """

    def __init__(self, uow_factory: PaymentUnitOfWorkFactory) -> None:
        """Получает фабрику атомарных операций через внедрение зависимостей."""
        self.uow_factory = uow_factory

    async def create(self, data: CreatePaymentCommand, key: str) -> Payment:
        """Создаёт платёж и событие либо возвращает результат одинакового запроса.

        Args:
            data: Валидированные и нормализованные параметры платежа.
            key: Обязательный клиентский ключ идемпотентности.

        Returns:
            Новый или существующий платёж с текущим статусом.

        Raises:
            IdempotencyConflictError: Ключ уже использован для другого тела запроса.
            PersistenceConflictError: Конфликт БД не связан с существующим ключом.

        """
        fingerprint = data.fingerprint()
        try:
            async with self.uow_factory() as uow:
                existing = await uow.payments.get_by_key(key)
                if existing is not None:
                    self._check_fingerprint(existing, fingerprint)
                    return existing
                payment = Payment.create(data, key)
                await uow.payments.add(payment)
                await uow.outbox.add(new_payment_event(payment.id))
                await uow.commit()
                return payment
        except PersistenceConflictError:
            # Другой запрос мог занять ключ между чтением и вставкой.
            # Предыдущий Unit of Work уже откатился; читаем победивший платёж
            # в новой транзакции, не используя аварийную SQLAlchemy-сессию.
            async with self.uow_factory() as uow:
                existing = await uow.payments.get_by_key(key)
                if existing is None:
                    raise
                self._check_fingerprint(existing, fingerprint)
                return existing

    async def get(self, payment_id: UUID) -> Payment:
        """Возвращает платёж по идентификатору.

        Args:
            payment_id: UUID платежа, выданный при создании.

        Raises:
            PaymentNotFoundError: В хранилище нет такого платежа.

        """
        async with self.uow_factory() as uow:
            payment = await uow.payments.get(payment_id)
            if payment is None:
                raise PaymentNotFoundError
            return payment

    @staticmethod
    def _check_fingerprint(payment: Payment, fingerprint: str) -> None:
        """Запрещает использовать один ключ для семантически разных запросов."""
        if payment.request_hash != fingerprint:
            raise IdempotencyConflictError
