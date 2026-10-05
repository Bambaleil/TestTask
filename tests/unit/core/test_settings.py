from pathlib import Path

import pytest
from pydantic import ValidationError

from payment_service.core.settings import ApiSettings, DatabaseSettings, WorkerSettings


def test_api_settings() -> None:
    """Создаёт настройки API без адреса и пароля RabbitMQ."""
    settings = ApiSettings(
        api_key="api-secret-at-least-16-chars",
        database_url="postgresql+asyncpg://user:password@database/payments",
    )
    assert "rabbitmq_url" not in settings.model_dump()
    assert "log_file" not in settings.model_dump()


def test_worker_settings() -> None:
    """Создаёт настройки consumer без клиентского API-ключа."""
    settings = WorkerSettings(
        database_url="postgresql+asyncpg://user:password@database/payments",
        rabbitmq_url="amqp://user:password@broker/",
    )
    assert "api_key" not in settings.model_dump()


def test_database_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Не подхватывает случайный .env из рабочей директории процесса."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql+asyncpg://secret@unexpected/database\n")
    with pytest.raises(ValidationError):
        DatabaseSettings()
    settings = DatabaseSettings(database_url="postgresql+asyncpg://user@expected/database")
    assert "expected" in settings.database_url.get_secret_value()


@pytest.mark.parametrize(
    "field", ["database_pool_size", "database_max_overflow", "database_pool_timeout"]
)
def test_database_settings_pool_limits(field: str) -> None:
    """Отклоняет неверные лимиты пула до создания сетевых подключений."""
    with pytest.raises(ValidationError):
        DatabaseSettings.model_validate(
            {"database_url": "postgresql+asyncpg://db/payments", field: -1}
        )
