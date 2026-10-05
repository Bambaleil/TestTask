"""Порты хранения, транзакции, шлюза и доставки уведомлений."""

from typing import Protocol
from uuid import UUID

from payment_service.core.db.contracts import UnitOfWork
from payment_service.modules.payments.domain.constants import PaymentStatus
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import WebhookPayload


class PaymentStore(Protocol):
    """Определяет необходимые бизнес-логике операции с платежами."""

    async def get(self, payment_id: UUID, *, for_update: bool = False) -> Payment | None:
        """Возвращает платёж; блокировка нужна для изменения состояния."""
        ...

    async def get_by_key(self, key: str) -> Payment | None:
        """Возвращает платёж по ключу исходного запроса."""
        ...

    async def add(self, payment: Payment) -> None:
        """Добавляет новый платёж в текущую транзакцию."""
        ...

    async def save(self, payment: Payment) -> None:
        """Сохраняет состояние существующего платежа."""
        ...


class PaymentUnitOfWork(UnitOfWork, Protocol):
    """Объединяет платёж и события в одной атомарной операции."""

    @property
    def payments(self) -> PaymentStore:
        """Предоставляет порт платежей текущей транзакции."""
        ...


class PaymentUnitOfWorkFactory(Protocol):
    """Создаёт независимые транзакции платёжного модуля."""

    def __call__(self) -> PaymentUnitOfWork:
        """Возвращает транзакцию с портами платежей и Outbox."""
        ...


class PaymentGateway(Protocol):
    """Определяет асинхронный контракт платёжного провайдера."""

    async def charge(self, payment: Payment) -> PaymentStatus:
        """Возвращает финальный результат оплаты.

        Args:
            payment: Платёж; его id используется как внешний ключ идемпотентности.

        Raises:
            Exception: Провайдер временно недоступен; допускается повторная попытка.

        """
        ...


class WebhookSender(Protocol):
    """Определяет контракт доставки результата клиенту."""

    async def send(self, url: str, payload: WebhookPayload) -> None:
        """Доставляет уведомление с сохранением ключа дедупликации.

        Args:
            url: Адрес получателя, нормализованный входным адаптером.
            payload: Финальный результат со стабильным event_id.

        Raises:
            Exception: Получатель не подтвердил доставку.

        """
        ...
