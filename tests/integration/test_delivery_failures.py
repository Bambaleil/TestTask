import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from faststream import AckPolicy
from faststream.rabbit import RabbitBroker, RabbitMessage
from sqlalchemy import select

from payment_service.core.db.connection import SessionFactory
from payment_service.core.events.models import OutboxEvent
from payment_service.core.events.outbox import OutboxDispatcher, OutboxOptions
from payment_service.core.events.rabbitmq import RabbitEventPublisher
from payment_service.modules.payments.dao.sqlalchemy import OutboxDAO
from payment_service.modules.payments.dao.tables import OutboxRecord
from payment_service.modules.payments.dao.unit_of_work import (
    PaymentUnitOfWork,
    PaymentUnitOfWorkFactory,
)
from payment_service.modules.payments.dao.webhook import HttpWebhookSender
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC
from payment_service.modules.payments.domain.contracts import WebhookSender
from payment_service.modules.payments.handlers import topology as messaging
from payment_service.modules.payments.handlers.rabbitmq import PaymentMessageHandler, decode_event
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate, PaymentEventMessage
from tests.fakes import FakeGateway, FakeWebhooks
from tests.integration.helpers import receive_dead_message

pytestmark = pytest.mark.integration


def build_dispatcher(sessions: SessionFactory, broker: RabbitBroker) -> OutboxDispatcher:
    """Соединяет PostgreSQL-Outbox с подтверждённой публикацией в тестовые exchanges."""
    return OutboxDispatcher(
        PaymentUnitOfWorkFactory(sessions),
        RabbitEventPublisher(
            broker, {NEW_TOPIC: messaging.PAYMENT_EXCHANGE, DEAD_TOPIC: messaging.DEAD_EXCHANGE}, 2
        ),
        OutboxOptions(poll_interval=0.01),
    )


@asynccontextmanager
async def running_consumer(
    sessions: SessionFactory, broker: RabbitBroker, gateway: FakeGateway, webhooks: WebhookSender
) -> AsyncIterator[None]:
    """Запускает настоящий consumer и диспетчер с управляемым HTTP-получателем."""
    handler = PaymentMessageHandler(
        PaymentProcessor(PaymentUnitOfWorkFactory(sessions), gateway, webhooks, 0.05), 0.01
    )
    broker.subscriber(
        messaging.PAYMENT_QUEUE,
        messaging.PAYMENT_EXCHANGE,
        ack_policy=AckPolicy.MANUAL,
        decoder=decode_event,
    )(handler.process_payment)
    await broker.start()
    task = asyncio.create_task(build_dispatcher(sessions, broker).run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_for_webhook(repository: PaymentRepository, payment_id: UUID) -> None:
    """Ожидает сохранённого результата доставки, а не истечения произвольной паузы."""
    async with asyncio.timeout(10):
        while (await repository.get(payment_id)).webhook_delivered_at is None:  # noqa: ASYNC110
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("failures", [1, 3], ids=["http-retry", "http-dlq"])
async def test_process_payment(
    sessions: SessionFactory,
    rabbit_broker: RabbitBroker,
    payment_data: PaymentCreate,
    failures: int,
) -> None:
    """HTTP 500 вызывает долговечные retry и DLQ без повторного обращения к шлюзу."""
    repository = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
    payment = await repository.create(payment_data.to_command(), "http-failures")
    requests: list[httpx.Request] = []
    gateway = FakeGateway()

    def respond(request: httpx.Request) -> httpx.Response:
        """Записывает настоящий HTTPX-запрос и управляет ответом внешнего получателя."""
        requests.append(request)
        return httpx.Response(500 if len(requests) <= failures else 204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        async with running_consumer(sessions, rabbit_broker, gateway, HttpWebhookSender(client)):
            if failures == 3:
                dead = await receive_dead_message(rabbit_broker)
                payload = json.loads(dead.body)
                assert payload["payment_id"] == str(payment.id)
                assert payload["attempt"] == 3
                assert payload["error"] == "HTTPStatusError"
                assert payload["status"] == "succeeded"
                await dead.ack()
            else:
                await wait_for_webhook(repository, payment.id)
    assert gateway.calls == 1
    assert len(requests) == min(failures + 1, 3)
    assert {request.headers["Idempotency-Key"] for request in requests} == {
        str(payment.webhook_event_id)
    }
    assert all(json.loads(request.content)["amount"] == "123.45" for request in requests)
    result = await repository.get(payment.id)
    assert result.status.value == "succeeded"
    assert (result.webhook_delivered_at is None) == (failures == 3)
    async with sessions() as session:
        events = list(await session.scalars(select(OutboxRecord)))
        retries = [
            event for event in events if event.topic == NEW_TOPIC and event.payload["attempt"] > 1
        ]
        assert len(events) == (4 if failures == 3 else 2)
        for event in retries:
            delay = (event.available_at - event.created_at).total_seconds()
            assert abs(delay - 0.05 * 2 ** (event.payload["attempt"] - 2)) < 0.02


class TestCommitAfterConfirm:
    """Проверки реального повторного RabbitMQ-сообщения после сбоя commit Outbox."""

    async def test_dispatch_batch(
        self, sessions: SessionFactory, rabbit_broker: RabbitBroker, payment_data: PaymentCreate
    ) -> None:
        """Повторная публикация сохраняет message_id, а consumer дедуплицирует оплату."""
        factory = PaymentUnitOfWorkFactory(sessions)
        payment = await PaymentRepository(factory).create(
            payment_data.to_command(), "confirm-commit"
        )
        with patch.object(PaymentUnitOfWork, "commit", side_effect=ConnectionError):
            with pytest.raises(ConnectionError):
                await build_dispatcher(sessions, rabbit_broker).dispatch_batch()
        async with sessions() as session:
            stored = (await session.scalars(select(OutboxRecord))).one()
            assert stored.published_at is None
        assert await build_dispatcher(sessions, rabbit_broker).dispatch_batch() == 1
        queue = await rabbit_broker.declare_queue(messaging.PAYMENT_QUEUE)
        gateway, webhooks = FakeGateway(), FakeWebhooks()
        processor = PaymentProcessor(factory, gateway, webhooks, 0.05)
        for _ in range(2):
            message = await queue.get(fail=False)
            assert message is not None
            assert message.message_id == str(stored.id)
            await processor.process(
                PaymentEventMessage.model_validate_json(message.body).to_event()
            )
            await message.ack()
        assert gateway.calls == len(webhooks.calls) == 1
        assert (await PaymentRepository(factory).get(payment.id)).webhook_delivered_at is not None


class TestNackAfterStorageFailure:
    """Проверки настоящей повторной доставки RabbitMQ при недолговечном retry."""

    async def test_process_payment(
        self, sessions: SessionFactory, rabbit_broker: RabbitBroker, payment_data: PaymentCreate
    ) -> None:
        """Сбой INSERT retry вызывает NACK; исходное событие доставляется повторно."""
        factory = PaymentUnitOfWorkFactory(sessions)
        repository = PaymentRepository(factory)
        payment = await repository.create(payment_data.to_command(), "storage-nack")
        gateway, webhooks = FakeGateway(), FakeWebhooks(failures=1)
        handler = PaymentMessageHandler(PaymentProcessor(factory, gateway, webhooks, 0.05), 0.01)
        deliveries: list[tuple[str | None, bool | None]] = []

        async def handle(body: object, message: RabbitMessage) -> None:
            """Записывает флаг redelivered настоящего AMQP-сообщения."""
            deliveries.append((message.message_id, message.raw_message.redelivered))
            await handler.process_payment(body, message)

        rabbit_broker.subscriber(
            messaging.PAYMENT_QUEUE,
            messaging.PAYMENT_EXCHANGE,
            ack_policy=AckPolicy.MANUAL,
            decoder=decode_event,
        )(handle)
        await rabbit_broker.start()
        original_add = OutboxDAO.add
        failed = False

        async def fail_first_retry(dao: OutboxDAO, event: OutboxEvent) -> None:
            """Срывает первый retry после INSERT, сохраняя работоспособность следующего."""
            nonlocal failed
            await original_add(dao, event)
            if not failed:
                failed = True
                raise ConnectionError

        with patch.object(OutboxDAO, "add", new=fail_first_retry):
            assert await build_dispatcher(sessions, rabbit_broker).dispatch_batch() == 1
            await wait_for_webhook(repository, payment.id)
        assert failed
        assert len(deliveries) == 2
        assert deliveries[0][0] == deliveries[1][0]
        assert [delivery[1] for delivery in deliveries] == [False, True]
        assert gateway.calls == 1
        assert len(webhooks.calls) == 2
        async with sessions() as session:
            events = list(await session.scalars(select(OutboxRecord)))
            assert len(events) == 1
            assert events[0].consumed_at is not None


class TestWebhookCommitFailure:
    """Проверки повторного HTTP-уведомления после успешного ответа и сбоя commit."""

    async def test_process(self, sessions: SessionFactory, payment_data: PaymentCreate) -> None:
        """Повторяет webhook с тем же ключом, сохраняя уже проведённую оплату."""
        factory = PaymentUnitOfWorkFactory(sessions)
        repository = PaymentRepository(factory)
        payment = await repository.create(payment_data.to_command(), "webhook-commit")
        async with sessions() as session:
            initial = (await session.scalars(select(OutboxRecord))).one()
        requests: list[httpx.Request] = []
        failed = False
        original_commit = PaymentUnitOfWork.commit

        def respond(request: httpx.Request) -> httpx.Response:
            """Имитирует получателя, который принял каждое уведомление."""
            requests.append(request)
            return httpx.Response(204)

        async def fail_notification_commit(uow: PaymentUnitOfWork) -> None:
            """Срывает commit после сохранения отметки успешного HTTP-вызова."""
            nonlocal failed
            current = await uow.payments.get(payment.id)
            if current.webhook_delivered_at is not None and not failed:
                failed = True
                raise ConnectionError
            await original_commit(uow)

        gateway = FakeGateway()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(PaymentUnitOfWork, "commit", new=fail_notification_commit):
                await PaymentProcessor(factory, gateway, HttpWebhookSender(client), 0.05).process(
                    PaymentEventMessage.model_validate(initial.payload).to_event()
                )
            saved = await repository.get(payment.id)
            assert failed and saved.webhook_delivered_at is None
            assert saved.status.value == "succeeded"
            async with sessions() as session:
                retry = (
                    await session.scalars(select(OutboxRecord).where(OutboxRecord.id != initial.id))
                ).one()
            # Новые адаптеры используют сохранённый результат оплаты и событие retry.
            await PaymentProcessor(factory, gateway, HttpWebhookSender(client), 0.05).process(
                PaymentEventMessage.model_validate(retry.payload).to_event()
            )
        assert gateway.calls == 1
        assert len(requests) == 2
        assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]
        assert requests[0].content == requests[1].content
        assert (await repository.get(payment.id)).webhook_delivered_at is not None
        async with sessions() as session:
            events = list(await session.scalars(select(OutboxRecord)))
            assert len(events) == 2
            assert all(event.consumed_at is not None for event in events)
