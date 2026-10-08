from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest

from payment_service.core.db.connection import SessionFactory
from payment_service.modules.payments.dao.unit_of_work import PaymentUnitOfWorkFactory
from payment_service.modules.payments.domain.constants import PaymentStatus
from payment_service.modules.payments.repository import PaymentRepository
from payment_service.modules.payments.schemas import PaymentCreate
from payment_service.modules.payments.views import create_payment
from payment_service.server import create_app
from tests.fakes import MemoryUnitOfWorkFactory, ServiceSettings


@pytest.fixture
async def client(
    sessions: SessionFactory, settings: ServiceSettings
) -> AsyncIterator[httpx.AsyncClient]:
    """Создаёт HTTP-клиент поверх ASGI без внешнего сервера."""
    app = create_app(settings, PaymentRepository(PaymentUnitOfWorkFactory(sessions)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": settings.api_key.get_secret_value()},
    ) as http_client:
        yield http_client


@pytest.mark.parametrize("key", [None, "wrong", "", "ключ"])
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/payments",
        "/api/v1/payments/00000000-0000-0000-0000-000000000000",
        "/docs",
        "/openapi.json",
    ],
)
async def test_require_api_key(client: httpx.AsyncClient, key: str | None, path: str) -> None:
    """Отклонить отсутствующий и неверный ключ на каждом эндпоинте."""
    client.headers.pop("X-API-Key")
    # HTTP-заголовки кодируются в ASCII, невалидные байты передаём явно.
    headers = {} if key is None else {b"X-API-Key": key.encode()}
    method = "POST" if path == "/api/v1/payments" else "GET"
    response = await client.request(method, path, headers=headers, json={})
    assert response.status_code == 401


@pytest.mark.parametrize("mode", ["new", "repeat", "conflict", "missing-key", "blank-key"])
async def test_create_payment(
    client: httpx.AsyncClient, payment_data: PaymentCreate, mode: str
) -> None:
    """Проверяет контракт 202, идемпотентность и обязательный заголовок."""
    body = payment_data.model_dump(mode="json")
    headers = {"Idempotency-Key": "api-test"}
    first = await client.post("/api/v1/payments", json=body, headers=headers)
    assert first.status_code == 202
    assert set(first.json()) == {"payment_id", "status", "created_at"}
    assert first.json()["status"] == "pending"
    if mode == "new":
        return
    if mode == "conflict":
        body["description"] = "Другой заказ"
    if mode == "missing-key":
        headers = {}
    if mode == "blank-key":
        headers = {"Idempotency-Key": "   "}
    second = await client.post("/api/v1/payments", json=body, headers=headers)
    expected = {"repeat": 202, "conflict": 409, "missing-key": 422, "blank-key": 422}[mode]
    assert second.status_code == expected
    if mode == "repeat":
        assert second.json()["payment_id"] == first.json()["payment_id"]


@pytest.mark.parametrize("mode", ["existing", "missing", "invalid-id"])
async def test_get_payment(
    client: httpx.AsyncClient, payment_data: PaymentCreate, mode: str
) -> None:
    """Проверяет подробный ответ, отсутствие платежа и некорректный UUID."""
    if mode == "existing":
        accepted = await client.post(
            "/api/v1/payments",
            json=payment_data.model_dump(mode="json"),
            headers={"Idempotency-Key": "get-test"},
        )
        payment_id = accepted.json()["payment_id"]
    else:
        payment_id = str(uuid4()) if mode == "missing" else "bad-id"
    response = await client.get(f"/api/v1/payments/{payment_id}")
    assert response.status_code == {"existing": 200, "missing": 404, "invalid-id": 422}[mode]
    if mode == "existing":
        data = response.json()
        assert data["amount"] == "123.45"
        assert data["metadata"] == payment_data.metadata
        assert data["processed_at"] is None
        assert data["webhook_delivered_at"] is None


async def test_openapi(client: httpx.AsyncClient) -> None:
    """Проверяет наличие статического API-ключа в схеме безопасности."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"


async def test_docs(client: httpx.AsyncClient) -> None:
    """Проверяет доступность защищённой страницы Swagger."""
    response = await client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text


async def test_health_router(client: httpx.AsyncClient) -> None:
    """Открывает liveness без ключа, сохраняя защиту платёжных маршрутов."""
    client.headers.pop("X-API-Key")
    assert (await client.get("/health/live")).status_code == 200
    assert (
        await client.get("/api/v1/payments/00000000-0000-0000-0000-000000000000")
    ).status_code == 401


class TestAcceptedPayment:
    """Проверки ответа HTTP-адаптера для нового и уже завершённого платежа."""

    @pytest.mark.parametrize("completed", [False, True], ids=["new", "completed-repeat"])
    async def test_create_payment(self, payment_data: PaymentCreate, completed: bool) -> None:
        """Возвращает исходные UUID и дату, сохраняя финальный статус повторного запроса."""
        factory = MemoryUnitOfWorkFactory()
        repository = PaymentRepository(factory)
        if completed:
            original = await repository.create(payment_data.to_command(), "accepted-payment")
            factory.state.payments[original.id].status = PaymentStatus.SUCCEEDED
        accepted = await create_payment(payment_data, "accepted-payment", repository)
        assert accepted.status == (PaymentStatus.SUCCEEDED if completed else PaymentStatus.PENDING)
        assert len(factory.state.payments) == len(factory.state.events) == 1
        saved = factory.state.payments[accepted.payment_id]
        assert accepted.created_at == saved.created_at
        assert next(iter(factory.state.events.values())).aggregate_id == accepted.payment_id
