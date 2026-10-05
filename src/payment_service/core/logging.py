"""Структурированные журналы stdout, независимые от сборщика инфраструктуры."""

import json
import logging
import sys
from datetime import UTC, datetime

from payment_service.core.settings import LoggingSettings


class JsonFormatter(logging.Formatter):
    """Сериализует запись одной строкой и маскирует настроенные секреты."""

    def __init__(self, service: str, secrets: tuple[str, ...] = ()) -> None:
        """Получает имя процесса и значения, запрещённые к выводу в журнал."""
        super().__init__()
        self.service = service
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        """Возвращает JSON с UTC-временем и безопасными полями записи."""
        payload: dict[str, str | int] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "service": self.service,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in ("payment_id", "event_id", "attempt", "error_type"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value if isinstance(value, int) else str(value)
        if record.exc_info and record.exc_info[0]:
            # Текст исключения может содержать DSN, URL или параметры SQL.
            payload["error_type"] = record.exc_info[0].__name__
        for name, value in payload.items():
            if isinstance(value, str):
                for secret in self.secrets:
                    value = value.replace(secret, "[REDACTED]")
                payload[name] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    settings: LoggingSettings, service: str, secrets: tuple[str, ...] = ()
) -> None:
    """Настраивает JSON-вывод процесса в stdout.

    Args:
        settings: Уровень журналов процесса.
        service: Стабильное имя процесса: api или consumer.
        secrets: Значения, которые запрещено выводить в журнал.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service, secrets))
    logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "faststream"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # HTTPX пишет URL webhook на INFO; данные получателя не нужны журналу.
    logging.getLogger("httpx").setLevel(logging.WARNING)
