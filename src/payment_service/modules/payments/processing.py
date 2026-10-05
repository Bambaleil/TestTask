"""Обработка платежа, повторные попытки и перевод событий в DLQ."""

import logging
from datetime import timedelta

from payment_service.core.events.models import OutboxEvent
from payment_service.core.utils.retry import retry_delay
from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.domain.constants import (
    DEAD_TOPIC,
    MAX_ATTEMPTS,
    NEW_TOPIC,
    Currency,
    PaymentStatus,
)
from payment_service.modules.payments.domain.contracts import (
    PaymentGateway,
    PaymentUnitOfWork,
    PaymentUnitOfWorkFactory,
    WebhookSender,
)
from payment_service.modules.payments.domain.entities import Payment
from payment_service.modules.payments.domain.events import (
    PaymentEvent,
    WebhookPayload,
    new_payment_event,
)
from payment_service.modules.payments.domain.exceptions import InvalidEventError

logger = logging.getLogger(__name__)


class PaymentProcessor:
    """Обрабатывает шлюз и webhook с защитой от дублирования сообщений."""

    def __init__(
        self,
        uow_factory: PaymentUnitOfWorkFactory,
        gateway: PaymentGateway,
        webhooks: WebhookSender,
        retry_base_delay: float,
    ) -> None:
        """Получает порты атомарного хранения, шлюза и уведомлений.

        Args:
            uow_factory: Создаёт отдельную транзакцию для каждой стадии.
            gateway: Возвращает финальный результат оплаты.
            webhooks: Доставляет результат клиенту по HTTP или через тестовый адаптер.
            retry_base_delay: Задержка после первой ошибки в секундах.
        """
        self.uow_factory = uow_factory
        self.gateway = gateway
        self.webhooks = webhooks
        self.retry_base_delay = retry_base_delay

    async def process(self, event: PaymentEvent) -> None:
        """Сохраняет результат оплаты и доставляет уведомление клиенту.

        При ошибке шлюза или уведомления следующая попытка либо DLQ сохраняется
        атомарно с завершением текущей. После этого транспорт может отправить ACK.

        Args:
            event: Валидированная прикладная попытка обработки платежа.

        Raises:
            InvalidEventError: Событие не совпадает с долговечной записью Outbox.
            Exception: Не удалось зафиксировать результат или следующую попытку в БД.
        """
        try:
            await self._charge(event)
            await self._notify(event)
            logger.info(
                "payment_processed",
                extra={"payment_id": event.payment_id, "event_id": event.event_id},
            )
        except InvalidEventError:
            raise
        except Exception as error:
            # ACK допустим только после сохранения retry/DLQ в Outbox.
            # Если сама БД недоступна, исключение уйдёт обработчику RabbitMQ.
            await self._record_failure(event, error)

    async def _lock(
        self, uow: PaymentUnitOfWork, event: PaymentEvent
    ) -> tuple[OutboxEvent, Payment]:
        """Блокирует событие и платёж в одинаковом порядке во всех стадиях.

        Args:
            uow: Общая транзакция платежа и события.
            event: Сообщение, проверяемое по записи Outbox.

        Returns:
            Заблокированное событие и соответствующий платёж.

        Raises:
            InvalidEventError: Идентификаторы или тело сообщения не совпадают.
        """
        stored = await uow.outbox.get_for_update(event.event_id)
        if stored is None or stored.topic != NEW_TOPIC or stored.payload != event.as_payload():
            raise InvalidEventError
        payment = await uow.payments.get(event.payment_id, for_update=True)
        if payment is None or stored.aggregate_id != event.payment_id:
            raise InvalidEventError
        return stored, payment

    async def _charge(self, event: PaymentEvent) -> None:
        """Фиксирует результат шлюза отдельно от доставки webhook."""
        async with self.uow_factory() as uow:
            stored, payment = await self._lock(uow, event)
            if stored.consumed_at is not None or payment.status != PaymentStatus.PENDING:
                return
            payment.status = await self.gateway.charge(payment)
            payment.processed_at = utcnow()
            await uow.payments.save(payment)
            await uow.commit()

    async def _notify(self, event: PaymentEvent) -> None:
        """Доставляет результат; при сбое commit уведомление может повториться."""
        async with self.uow_factory() as uow:
            stored, payment = await self._lock(uow, event)
            if stored.consumed_at is not None:
                return
            if payment.webhook_delivered_at is None:
                if payment.processed_at is None:
                    raise InvalidEventError
                await self.webhooks.send(
                    payment.webhook_url,
                    WebhookPayload(
                        event_id=payment.webhook_event_id,
                        payment_id=payment.id,
                        status=PaymentStatus(payment.status),
                        amount=payment.amount,
                        currency=Currency(payment.currency),
                        metadata=payment.metadata,
                        processed_at=payment.processed_at,
                    ),
                )
                payment.webhook_delivered_at = utcnow()
            payment.last_error = None
            stored.consumed_at = utcnow()
            await uow.payments.save(payment)
            await uow.outbox.save(stored)
            await uow.commit()

    async def _record_failure(self, event: PaymentEvent, error: Exception) -> None:
        """Завершает текущую попытку и атомарно сохраняет retry либо событие DLQ.

        Args:
            event: Неуспешная прикладная попытка обработки.
            error: Причина сбоя; сохраняется только имя класса исключения.
        """
        async with self.uow_factory() as uow:
            stored, payment = await self._lock(uow, event)
            if stored.consumed_at is not None:
                return
            # Не сохраняем URL, заголовки и тела ответов из текста исключения.
            error_name = type(error).__name__
            payment.last_error = error_name
            stored.last_error = error_name
            stored.consumed_at = utcnow()
            followup = new_payment_event(payment.id, min(event.attempt + 1, MAX_ATTEMPTS))
            if event.attempt < MAX_ATTEMPTS:
                followup.available_at = utcnow() + timedelta(
                    seconds=retry_delay(event.attempt, self.retry_base_delay)
                )
            else:
                # Ошибка уведомления не превращает успешный платёж в failed.
                if payment.status == PaymentStatus.PENDING:
                    payment.status = PaymentStatus.FAILED
                    payment.processed_at = utcnow()
                followup.topic = DEAD_TOPIC
                followup.payload.update(
                    original_event_id=str(event.event_id),
                    error=error_name,
                    status=payment.status,
                )
            await uow.payments.save(payment)
            await uow.outbox.save(stored)
            await uow.outbox.add(followup)
            await uow.commit()
        logger.warning(
            "payment_attempt_failed",
            extra={
                "payment_id": event.payment_id,
                "event_id": event.event_id,
                "attempt": event.attempt,
                "error_type": type(error).__name__,
            },
        )
