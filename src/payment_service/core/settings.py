"""Настройки приложения из переменных окружения."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Читает настройки из окружения или явно переданного каталога секретов."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


class DatabaseSettings(RuntimeSettings):
    """Задаёт подключение и ограничения пула для процесса или миграции."""

    database_url: SecretStr = Field(min_length=1)
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout: float = Field(default=5, gt=0, le=60)


class LoggingSettings(RuntimeSettings):
    """Задаёт уровень структурированных журналов процесса."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class ApiSettings(DatabaseSettings, LoggingSettings):
    """Содержит настройки HTTP API без учётных данных брокера."""

    api_key: SecretStr = Field(min_length=16)


class WorkerSettings(DatabaseSettings, LoggingSettings):
    """Содержит настройки обработки событий без клиентского API-ключа."""

    rabbitmq_url: SecretStr = Field(min_length=1)
    outbox_poll_interval: float = Field(default=0.5, gt=0, le=60)
    outbox_batch_size: int = Field(default=50, ge=1, le=1000)
    publish_timeout: float = Field(default=5, gt=0, le=30)
    webhook_timeout: float = Field(default=5, gt=0, le=30)
    retry_base_delay: float = Field(default=2, gt=0, le=300)
    worker_health_port: int = Field(default=8081, ge=1, le=65535)
