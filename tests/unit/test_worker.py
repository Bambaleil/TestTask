import asyncio
from contextlib import nullcontext
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from payment_service import worker
from payment_service.container import WorkerContainer
from payment_service.core.events.outbox import OutboxDispatcher
from payment_service.core.events.rabbitmq import create_broker
from tests.fakes import ServiceSettings


@pytest.mark.parametrize(
    "mode", ["running", "finished", "body-error", "connect-error", "topology-error"]
)
async def test_create_app(
    settings: ServiceSettings, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Проверяет readiness consumer и освобождение ресурсов при остановке и сбое запуска."""
    monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
    monkeypatch.setenv("RABBITMQ_URL", settings.rabbitmq_url.get_secret_value())
    engine = create_async_engine("sqlite+aiosqlite://")
    broker = create_broker(settings)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def dispatch() -> None:
        """Предоставляет управляемую фоновую задачу без опроса внешней базы."""
        started.set()
        if mode == "finished":
            return
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with (
        patch.object(worker, "create_engine", return_value=engine),
        patch.object(worker, "create_broker", return_value=broker),
        patch.object(broker, "connect", new_callable=AsyncMock) as connect,
        patch.object(broker, "stop", new_callable=AsyncMock) as stop,
        patch.object(broker, "ping", new_callable=AsyncMock, return_value=True),
        patch.object(worker, "declare_topology", new_callable=AsyncMock) as topology,
        patch.object(OutboxDispatcher, "run", side_effect=dispatch) as run_dispatcher,
        patch.object(WorkerContainer, "build", wraps=WorkerContainer.build) as build_container,
        patch.object(
            AsyncEngine, "dispose", autospec=True, side_effect=AsyncEngine.dispose
        ) as dispose,
    ):
        if mode == "connect-error":
            connect.side_effect = RuntimeError("startup failed")
        if mode == "topology-error":
            topology.side_effect = RuntimeError("startup failed")
        app = worker.create_app()
        # Проверяем маршруты через настоящее ASGI-приложение, без запуска сокета.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            expectation = (
                pytest.raises(RuntimeError, match="failed") if "error" in mode else nullcontext()
            )
            with expectation:
                async with app.lifespan_context():
                    async with asyncio.timeout(1):
                        await started.wait()
                    response = await client.get("/health/ready")
                    assert response.status_code == (503 if mode == "finished" else 200)
                    assert response.json()["checks"] == {
                        "database": True,
                        "rabbitmq": True,
                        "outbox": mode != "finished",
                    }
                    if mode == "body-error":
                        raise RuntimeError("request failed")
            assert (await client.get("/health/ready")).status_code == 503
        dispose.assert_awaited_once_with(engine)
        stop.assert_awaited_once()
        webhook_client = build_container.call_args.args[2]
        assert webhook_client.is_closed
        if mode in {"connect-error", "topology-error"}:
            run_dispatcher.assert_not_awaited()
            assert not started.is_set()
        else:
            run_dispatcher.assert_awaited_once()
            assert cancelled.is_set() == (mode != "finished")
        if mode == "connect-error":
            topology.assert_not_awaited()
        else:
            topology.assert_awaited_once_with(broker)


def test_main(settings: ServiceSettings) -> None:
    """Запускает Uvicorn на health-порту и передаёт секреты только фильтру логов."""
    app = Mock()
    with (
        patch.object(worker, "WorkerSettings", return_value=settings),
        patch.object(worker, "configure_logging") as configure,
        patch.object(worker, "create_app", return_value=app) as build_app,
        patch.object(worker.uvicorn, "run") as run,
    ):
        worker.main()
    build_app.assert_called_once_with(settings)
    configure.assert_called_once_with(
        settings,
        "consumer",
        (settings.database_url.get_secret_value(), settings.rabbitmq_url.get_secret_value()),
    )
    run.assert_called_once_with(
        app,
        host="0.0.0.0",  # noqa: S104 — проверка параметров контейнерного сервера.
        port=settings.worker_health_port,
        log_config=None,
    )
