"""Сборка HTTP-приложения из ядра и платёжного модуля."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from importlib.metadata import version

import uvicorn
from fastapi import Depends, FastAPI

from payment_service.container import build_payment_repository
from payment_service.core.auth.dependencies import require_api_key
from payment_service.core.db.connection import create_engine
from payment_service.core.health import HealthRegistry, database_ready, health_router
from payment_service.core.logging import configure_logging
from payment_service.core.routes import router as core_router
from payment_service.core.settings import ApiSettings
from payment_service.modules.payments.module import register_http
from payment_service.modules.payments.repository import PaymentRepository


def create_app(
    settings: ApiSettings | None = None, repository: PaymentRepository | None = None
) -> FastAPI:
    """Собирает HTTP API и управляет временем жизни пула БД.

    Args:
        settings: Явные настройки; по умолчанию читаются из окружения.
        repository: Изолированные бизнес-операции для тестов; иначе используется PostgreSQL.

    Returns:
        Приложение с зарегистрированными системными и платёжными маршрутами.

    """
    resolved_settings = settings or ApiSettings()
    registry = HealthRegistry()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """Подключает зависимости API и освобождает пул при завершении процесса."""
        if repository is not None:
            yield
            return
        engine = create_engine(resolved_settings)
        registry.checks["database"] = partial(database_ready, engine)
        application.state.payment_repository = build_payment_repository(engine)
        logging.getLogger(__name__).info("api_started")
        try:
            yield
        finally:
            registry.checks.clear()
            await engine.dispose()

    application = FastAPI(
        title="Асинхронный сервис платежей",
        version=version("payment-service"),
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.settings = resolved_settings
    application.include_router(health_router(registry))
    application.include_router(core_router, dependencies=[Depends(require_api_key)])
    # Repository будет установлен lifespan; маршруты и ошибки регистрируем один раз.
    register_http(application, repository)
    return application


def main() -> None:
    """Запускает один HTTP-процесс; число реплик задаёт инфраструктура."""
    settings = ApiSettings()
    configure_logging(
        settings,
        "api",
        (settings.api_key.get_secret_value(), settings.database_url.get_secret_value()),
    )
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000, log_config=None)  # noqa: S104
