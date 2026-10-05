"""Изолированные схемы PostgreSQL и очереди RabbitMQ для интеграционных тестов."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from payment_service.core.db.connection import SessionFactory, create_session_factory
from payment_service.core.events.rabbitmq import create_broker
from payment_service.modules.payments.domain.constants import DEAD_TOPIC, NEW_TOPIC
from payment_service.modules.payments.handlers import topology as messaging
from tests.fakes import ServiceSettings

ALEMBIC_CONFIG = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    """Применить настоящие миграции к новой схеме и удалить только её после теста."""
    url = os.getenv("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("Для PostgreSQL-тестов задайте TEST_DATABASE_URL")
    schema = f"payment_test_{uuid4().hex}"
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        config = Config(str(ALEMBIC_CONFIG))

        def migrate(connection: Connection) -> None:
            """Передать Alembic соединение с изолированным search_path."""
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.fixture
async def sessions(postgres_engine: AsyncEngine) -> SessionFactory:
    """Переопределить SQLite-фабрику фабрикой сессий PostgreSQL."""
    return create_session_factory(postgres_engine)


@pytest.fixture
async def rabbit_broker(
    monkeypatch: pytest.MonkeyPatch, settings: ServiceSettings
) -> AsyncIterator[RabbitBroker]:
    """Создаёт отдельные exchanges/queues; очереди сервиса не затрагиваются."""
    url = os.getenv("TEST_RABBITMQ_URL")
    if url is None:
        pytest.skip("Для RabbitMQ-тестов задайте TEST_RABBITMQ_URL")
    suffix = uuid4().hex
    exchange = RabbitExchange(f"test.payments.{suffix}", durable=True)
    dead_exchange = RabbitExchange(f"test.payments.dlx.{suffix}", durable=True)
    queue = RabbitQueue(
        f"test.payments.new.{suffix}",
        durable=True,
        routing_key=NEW_TOPIC,
        arguments={
            "x-dead-letter-exchange": dead_exchange.name,
            "x-dead-letter-routing-key": DEAD_TOPIC,
        },
    )
    dead_queue = RabbitQueue(f"test.payments.dead.{suffix}", durable=True, routing_key=DEAD_TOPIC)
    monkeypatch.setattr(messaging, "PAYMENT_EXCHANGE", exchange)
    monkeypatch.setattr(messaging, "DEAD_EXCHANGE", dead_exchange)
    monkeypatch.setattr(messaging, "PAYMENT_QUEUE", queue)
    monkeypatch.setattr(messaging, "DEAD_QUEUE", dead_queue)
    settings = settings.model_copy(update={"rabbitmq_url": settings.rabbitmq_url.__class__(url)})
    broker = create_broker(settings)
    try:
        await broker.connect()
        await messaging.declare_topology(broker)
        yield broker
    finally:
        await broker.stop()
        cleanup = create_broker(settings)
        try:
            await cleanup.connect()
            await (await cleanup.declare_queue(queue)).delete()
            await (await cleanup.declare_queue(dead_queue)).delete()
            await (await cleanup.declare_exchange(exchange)).delete()
            await (await cleanup.declare_exchange(dead_exchange)).delete()
        finally:
            await cleanup.stop()
