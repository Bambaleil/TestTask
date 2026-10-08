from contextlib import nullcontext
from unittest.mock import Mock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from payment_service import server
from payment_service.core.db.connection import SessionFactory
from payment_service.core.db.models import Base
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate
from tests.fakes import ServiceSettings


@pytest.mark.parametrize("fail_request", [False, True], ids=["shutdown", "request-error"])
async def test_create_app(
    settings: ServiceSettings, payment_data: PaymentCreate, fail_request: bool
) -> None:
    """Создаёт зависимости API, обслуживает платёж и закрывает пул даже после ошибки."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    with patch.object(server, "create_engine", return_value=engine) as build_engine:
        with patch.object(
            AsyncEngine, "dispose", autospec=True, side_effect=AsyncEngine.dispose
        ) as dispose:
            app = server.create_app(settings)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                assert (await client.get("/health/ready")).status_code == 503
                expectation = (
                    pytest.raises(RuntimeError, match="request failed")
                    if fail_request
                    else nullcontext()
                )
                with expectation:
                    async with app.router.lifespan_context(app):
                        build_engine.assert_called_once_with(settings)
                        assert (await client.get("/health/ready")).json()["checks"] == {
                            "database": True
                        }
                        client.headers["X-API-Key"] = settings.api_key.get_secret_value()
                        response = await client.post(
                            "/api/v1/payments",
                            json=payment_data.model_dump(mode="json"),
                            headers={"Idempotency-Key": "lifespan-payment"},
                        )
                        assert response.status_code == 202
                        payment_id = response.json()["payment_id"]
                        details = await client.get(f"/api/v1/payments/{payment_id}")
                        assert details.status_code == 200
                        assert details.json()["amount"] == "123.45"
                        if fail_request:
                            raise RuntimeError("request failed")
                dispose.assert_awaited_once_with(engine)
                assert (await client.get("/health/ready")).status_code == 503


class TestInjectedRepository:
    """Проверки запуска API с явно предоставленными бизнес-операциями."""

    async def test_create_app(
        self, sessions: SessionFactory, settings: ServiceSettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Читает настройки окружения и сохраняет внедрённый repository без нового пула."""
        monkeypatch.setenv("API_KEY", settings.api_key.get_secret_value())
        monkeypatch.setenv("DATABASE_URL", settings.database_url.get_secret_value())
        repository = PaymentRepository(PaymentUnitOfWorkFactory(sessions))
        with patch.object(server, "create_engine") as build_engine:
            app = server.create_app(repository=repository)
            async with app.router.lifespan_context(app):
                assert app.state.payment_repository is repository
            build_engine.assert_not_called()


def test_main(settings: ServiceSettings) -> None:
    """Передаёт настройки, секреты для маскирования и ASGI-приложение серверу Uvicorn."""
    app = Mock()
    with (
        patch.object(server, "ApiSettings", return_value=settings),
        patch.object(server, "configure_logging") as configure,
        patch.object(server, "create_app", return_value=app) as build_app,
        patch.object(server.uvicorn, "run") as run,
    ):
        server.main()
    build_app.assert_called_once_with(settings)
    configure.assert_called_once_with(
        settings,
        "api",
        (settings.api_key.get_secret_value(), settings.database_url.get_secret_value()),
    )
    run.assert_called_once_with(app, host="0.0.0.0", port=8000, log_config=None)  # noqa: S104
