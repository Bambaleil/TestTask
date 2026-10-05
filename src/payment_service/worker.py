"""Сборка фонового приложения из доменного модуля и адаптеров."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from functools import partial

import httpx
import uvicorn
from fastapi import FastAPI
from faststream import AckPolicy
from faststream.asgi import AsgiFastStream

from payment_service.container import WorkerContainer
from payment_service.core.db.connection import create_engine
from payment_service.core.events.rabbitmq import create_broker
from payment_service.core.health import HealthRegistry, database_ready, health_router
from payment_service.core.logging import configure_logging
from payment_service.core.settings import WorkerSettings
from payment_service.modules.payments.handlers.rabbitmq import PaymentMessageHandler, decode_event
from payment_service.modules.payments.handlers.topology import (
    PAYMENT_EXCHANGE,
    PAYMENT_QUEUE,
    declare_topology,
)


def create_app(settings: WorkerSettings | None = None) -> AsgiFastStream:
    """Собирает consumer и управляет его инфраструктурными ресурсами.

    Args:
        settings: Явные настройки; по умолчанию читаются из окружения.

    Returns:
        FastStream-приложение с платёжным обработчиком и фоновым Outbox.
    """
    resolved_settings = settings or WorkerSettings()
    broker = create_broker(resolved_settings)
    engine = create_engine(resolved_settings)
    client = httpx.AsyncClient(
        timeout=resolved_settings.webhook_timeout,
        follow_redirects=False,
        trust_env=False,
    )
    container = WorkerContainer.build(engine, broker, client, resolved_settings)
    registry = HealthRegistry(
        {"database": partial(database_ready, engine), "rabbitmq": partial(broker.ping, 1)}
    )
    health_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    health_app.include_router(health_router(registry))

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        """Подготавливает топологию и освобождает ресурсы при завершении процесса."""
        task: asyncio.Task[None] | None = None
        try:
            await broker.connect()
            await declare_topology(broker)
            task = asyncio.create_task(container.dispatcher.run(), name="outbox-dispatcher")

            async def outbox_ready() -> bool:
                """Подтверждает, что фоновая задача Outbox не завершилась."""
                return task is not None and not task.done()

            registry.checks["outbox"] = outbox_ready
            logging.getLogger(__name__).info("consumer_started")
            yield
        finally:
            registry.checks.clear()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await client.aclose()
            await engine.dispose()
            await broker.stop()

    handler = PaymentMessageHandler(container.module.processor, resolved_settings.retry_base_delay)
    broker.subscriber(
        PAYMENT_QUEUE, PAYMENT_EXCHANGE, ack_policy=AckPolicy.MANUAL, decoder=decode_event
    )(handler.process_payment)

    return AsgiFastStream(
        broker,
        lifespan=lifespan,
        asgi_routes=[("/health/live", health_app), ("/health/ready", health_app)],
    )


def main() -> None:
    """Запускает consumer с обработкой сигналов завершения FastStream."""
    settings = WorkerSettings()
    configure_logging(
        settings,
        "consumer",
        (settings.database_url.get_secret_value(), settings.rabbitmq_url.get_secret_value()),
    )
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 — порт доступен только внутри сети контейнеров.
        port=settings.worker_health_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
