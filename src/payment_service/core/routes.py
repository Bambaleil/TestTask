"""Системные HTTP-маршруты ядра, защищённые общим API-ключом."""

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()


@router.get("/openapi.json", include_in_schema=False)
async def openapi(request: Request) -> JSONResponse:
    """Возвращает схему API подключённых модулей.

    - *Rights*: действительный X-API-Key.
    """
    return JSONResponse(request.app.openapi())


@router.get("/docs", include_in_schema=False)
async def docs() -> HTMLResponse:
    """Возвращает страницу интерактивной документации API.

    - *Rights*: действительный X-API-Key.
    """
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Документация платежей")
