"""Проверки работоспособности процесса и готовности инфраструктуры."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

Probe = Callable[[], Awaitable[bool]]


@dataclass
class HealthRegistry:
    """Объединяет независимые проверки с ограничением времени выполнения.

    Attributes:
        checks: Имена компонентов и асинхронные проверки их готовности.
        timeout: Максимальное время одной проверки в секундах.
    """

    checks: dict[str, Probe] = field(default_factory=dict)
    timeout: float = 3

    async def readiness(self) -> dict[str, bool]:
        """Возвращает состояние компонентов, скрывая тексты технических ошибок."""

        async def evaluate(probe: Probe) -> bool:
            """Преобразует отказ и таймаут зависимости в отрицательный результат."""
            try:
                async with asyncio.timeout(self.timeout):
                    return await probe()
            except Exception:
                return False

        values = await asyncio.gather(*(evaluate(probe) for probe in self.checks.values()))
        return dict(zip(self.checks, values, strict=True))


async def database_ready(engine: AsyncEngine) -> bool:
    """Проверяет получение соединения из пула и выполнение запроса БД."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


def health_router(registry: HealthRegistry) -> APIRouter:
    """Создаёт публичные маршруты состояния без раскрытия настроек и секретов.

    Args:
        registry: Проверки зависимостей конкретного процесса.

    Returns:
        Маршруты liveness и readiness для Docker или оркестратора.
    """
    router = APIRouter(prefix="/health", tags=["Состояние"])

    @router.get("/live", include_in_schema=False)
    async def live() -> dict[str, str]:
        """Подтверждает, что HTTP-процесс отвечает на запросы."""
        return {"status": "ok"}

    @router.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Возвращает 200 при готовности всех зависимостей, иначе 503."""
        checks = await registry.readiness()
        healthy = bool(checks) and all(checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "unavailable", "checks": checks},
            status_code=200 if healthy else 503,
        )

    return router
