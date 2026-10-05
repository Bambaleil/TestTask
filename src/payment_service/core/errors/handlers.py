"""Преобразование ошибок подключённых модулей в HTTP-ответы."""

from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from payment_service.core.errors.exceptions import BusinessError


@dataclass(frozen=True)
class ErrorResponse:
    """Задаёт HTTP-представление зарегистрированной бизнес-ошибки."""

    status_code: int
    detail: str


def install_error_handlers(
    app: FastAPI, mappings: Mapping[type[BusinessError], ErrorResponse]
) -> None:
    """Подключает перевод доменных ошибок в ответы, не раскрывая внутренние данные.

    Args:
        app: HTTP-приложение, принимающее запросы.
        mappings: Типы ошибок и публичные сообщения, заданные модулями.

    """
    for error_type, response in mappings.items():
        app.add_exception_handler(error_type, _make_handler(response))


def _make_handler(
    response: ErrorResponse,
) -> Callable[[Request, Exception], Coroutine[object, object, JSONResponse]]:
    """Создаёт обработчик с зафиксированным публичным ответом."""

    async def handle_error(request: Request, error: Exception) -> JSONResponse:
        """Возвращает публичное сообщение вместо технического текста исключения."""
        return JSONResponse(status_code=response.status_code, content={"detail": response.detail})

    return handle_error
