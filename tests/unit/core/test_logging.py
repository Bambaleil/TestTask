import json
import logging
import sys
from unittest.mock import Mock

import pytest

from payment_service.core.logging import JsonFormatter, configure_logging
from tests.fakes import ServiceSettings


@pytest.mark.parametrize("exception", [False, True])
def test_format(exception: bool) -> None:
    """Проверяет JSON, маскирование секретов и безопасное описание исключения."""
    formatter = JsonFormatter("consumer", ("secret-token",))
    record = logging.LogRecord(
        "payments", logging.WARNING, __file__, 1, "%s", ("secret-token",), None
    )
    record.payment_id = "payment-123"
    record.attempt = 2
    record.metadata = {"secret": "should-not-appear"}
    if exception:
        error = RuntimeError("sensitive-url")
        record.exc_info = (RuntimeError, error, None)
    output = formatter.format(record)
    payload = json.loads(output)
    assert payload["service"] == "consumer"
    assert payload["level"] == "WARNING"
    assert payload["message"] == "[REDACTED]"
    assert payload["attempt"] == 2
    assert "should-not-appear" not in output
    assert "sensitive-url" not in output
    assert payload.get("error_type") == ("RuntimeError" if exception else None)


def test_configure_logging(settings: ServiceSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет JSON-вывод без файлов и подключений к сборщику журналов."""
    basic_config = Mock()
    monkeypatch.setattr(logging, "basicConfig", basic_config)
    configure_logging(settings, "api", (settings.api_key.get_secret_value(),))
    handlers = basic_config.call_args.kwargs["handlers"]
    try:
        assert len(handlers) == 1
        assert handlers[0].stream is sys.stdout
        record = logging.LogRecord(
            "payments", logging.INFO, __file__, 1, settings.api_key.get_secret_value(), (), None
        )
        assert json.loads(handlers[0].format(record))["message"] == "[REDACTED]"
    finally:
        for handler in handlers:
            handler.close()
