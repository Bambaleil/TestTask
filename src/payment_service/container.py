"""Единая точка связывания портов приложения с конкретными адаптерами."""

from dataclasses import dataclass

import httpx
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncEngine

from payment_service.core.db.connection import create_session_factory
from payment_service.core.events.outbox import OutboxDispatcher, OutboxOptions
from payment_service.core.events.rabbitmq import RabbitEventPublisher
from payment_service.core.settings import WorkerSettings
from payment_service.modules.payments.dao.gateway import SimulatedGateway
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.dao.webhook import HttpWebhookSender
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC
from payment_service.modules.payments.handlers.topology import DEAD_EXCHANGE, PAYMENT_EXCHANGE
from payment_service.modules.payments.module import PaymentModule
from payment_service.modules.payments.repository import PaymentRepository


def build_payment_repository(engine: AsyncEngine) -> PaymentRepository:
    """Подключает бизнес-операции API к фабрике PostgreSQL-транзакций."""
    return PaymentRepository(PaymentUnitOfWorkFactory(create_session_factory(engine)))


@dataclass(frozen=True)
class WorkerContainer:
    """Хранит зависимости consumer, собранные в одном месте."""

    module: PaymentModule
    dispatcher: OutboxDispatcher

    @classmethod
    def build(
        cls,
        engine: AsyncEngine,
        broker: RabbitBroker,
        client: httpx.AsyncClient,
        settings: WorkerSettings,
    ) -> "WorkerContainer":
        """Связывает доменные порты с PostgreSQL, RabbitMQ и HTTPX.

        Args:
            engine: Общий пул асинхронных соединений PostgreSQL.
            broker: Брокер для публикации и обработки сообщений.
            client: HTTP-клиент с заданным таймаутом.
            settings: Проверенные параметры фоновых операций.

        Returns:
            Consumer-модуль и диспетчер, использующие одну фабрику транзакций.

        """
        uow_factory = PaymentUnitOfWorkFactory(create_session_factory(engine))
        module = PaymentModule.build(
            uow_factory,
            SimulatedGateway(),
            HttpWebhookSender(client),
            settings.retry_base_delay,
        )
        publisher = RabbitEventPublisher(
            broker,
            {NEW_TOPIC: PAYMENT_EXCHANGE, DEAD_TOPIC: DEAD_EXCHANGE},
            settings.publish_timeout,
        )
        dispatcher = OutboxDispatcher(
            uow_factory,
            publisher,
            OutboxOptions(settings.outbox_batch_size, settings.outbox_poll_interval),
        )
        return cls(module, dispatcher)
