"""Проверка статического API-ключа на всех HTTP-маршрутах."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from payment_service.core.settings import ApiSettings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    """Проверяет статический ключ без утечки времени сравнения."""
    settings: ApiSettings = request.app.state.settings
    expected = settings.api_key.get_secret_value()
    if api_key is None or not secrets.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный API-ключ")
