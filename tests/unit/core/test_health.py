from functools import partial

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from payment_service.core.health import HealthRegistry, database_ready, health_router


@pytest.mark.parametrize("mode", ["ok", "false", "exception", "timeout"])
async def test_readiness(mode: str) -> None:
    """Проверяет отказ и таймаут без передачи секретов из исключения в ответ."""

    async def probe() -> bool:
        """Эмулирует успешную или недоступную инфраструктуру."""
        if mode == "exception":
            raise RuntimeError("secret-dsn")
        if mode == "timeout":
            import asyncio

            await asyncio.sleep(1)
        return mode == "ok"

    registry = HealthRegistry({"dependency": probe}, timeout=0.01)
    assert await registry.readiness() == {"dependency": mode == "ok"}


@pytest.mark.parametrize("mode", ["ready", "failed", "uninitialized"])
async def test_health_router(mode: str) -> None:
    """Разделяет liveness процесса и readiness его зависимостей."""

    async def probe() -> bool:
        """Возвращает состояние тестовой зависимости."""
        return mode == "ready"

    registry = HealthRegistry({} if mode == "uninitialized" else {"database": probe})
    app = FastAPI()
    app.include_router(health_router(registry))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        live = await client.get("/health/live")
        assert live.status_code == 200
        ready = await client.get("/health/ready")
        assert ready.status_code == (200 if mode == "ready" else 503)
        assert "secret" not in ready.text


async def test_database_ready() -> None:
    """Проверяет readiness реальным SQL-запросом из асинхронного пула."""
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        registry = HealthRegistry({"database": partial(database_ready, engine)})
        assert await registry.readiness() == {"database": True}
    finally:
        await engine.dispose()
