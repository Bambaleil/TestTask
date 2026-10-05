# Асинхронный сервис платежей

[![CI](https://github.com/Bambaleil/TestTask/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/Bambaleil/TestTask/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/github/Bambaleil/TestTask/branch/main/graph/badge.svg)](https://codecov.io/github/Bambaleil/TestTask)

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)
![RabbitMQ](https://img.shields.io/badge/RabbitMQ-4-FF6600?logo=rabbitmq&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff&logoColor=black)
![mypy](https://img.shields.io/badge/mypy-strict-2A6DB0)
[![uv](https://img.shields.io/badge/packaging-uv-FFD43B)](https://github.com/astral-sh/uv)
[![pytest](https://img.shields.io/badge/pytest-8.3%2B-0A9EDC?logo=pytest)](https://docs.pytest.org/)
[![pytest-cov](https://img.shields.io/badge/pytest--cov-6%2B-0A9EDC)](https://pytest-cov.readthedocs.io/)

| Область | Технологии |
| --- | --- |
| API и настройки | FastAPI, Pydantic, Uvicorn |
| Данные и миграции | PostgreSQL, SQLAlchemy Async, asyncpg, Alembic |
| События и уведомления | RabbitMQ, FastStream, HTTPX |
| Качество и тесты | Ruff, mypy, pytest, pytest-asyncio, pytest-cov, pre-commit |
| Окружение и CI | uv, Docker Compose, GitHub Actions, Codecov |
| Документация и локальные логи | MkDocs, mkdocstrings, Grafana, Loki, Alloy |

## Локальный запуск

```bash
cp deploy/local/.env.example deploy/local/.env
make local-up
make local-status
make local-logs
```

API: `http://localhost:8000`. Платёжные маршруты, `/docs` и `/openapi.json`
требуют `X-API-Key`; создание платежа — также `Idempotency-Key`.
`/health/live` и `/health/ready` доступны без ключа.
[Примеры запросов](docs/guides/quickstart.md).

Опциональная локальная Grafana:

```bash
make observability
```

Grafana: `http://localhost:3000`, учётные данные из `deploy/local/.env`.
Конфигурации и дашборд находятся в `deploy/local/observability`, отдельный
Compose-файл добавляет сбор stdout Docker через Alloy. Остановка стенда
с сохранением данных: `make local-down`.

## Развёртывание

Один образ содержит команды `payment-api`, `payment-worker` и `alembic`.
API требует `API_KEY` и `DATABASE_URL`; consumer — `DATABASE_URL` и
`RABBITMQ_URL`; миграции — только `DATABASE_URL`. `.env` не загружается
приложением автоматически. Образ запускается от UID 10001 и поддерживает
файловую систему только для чтения.

`deploy/production/compose.yaml` — пример запуска API/consumer с внешними
зависимостями и отдельным шагом миграции. Образ передаётся через `PAYMENT_IMAGE`;
демонстрационные пароли и Grafana в этот файл не включены.
[Порядок выпуска и инфраструктурные контракты](docs/ops/deployment.md).

## Архитектура

Ядро находится в `core`, предметная область — в `modules/payments`;
Доменные сущности и Protocol-порты независимы от ORM, HTTP и брокера.
Адаптеры связываются в `container.py`; Unit of Work задаёт атомарность.

- [Структура проекта](docs/tech/project_structure.md).
- [Слои и паттерны](docs/tech/application_layers.md).
- [Надёжность и сбои](docs/ops/reliability.md).
- [Логи и healthcheck](docs/ops/observability.md).

## Проверки

```bash
uv sync --frozen --group docs
make check                 # Ruff, mypy, изолированные тесты
make docker-test           # Все тесты с настоящими PostgreSQL и RabbitMQ
make format
make hooks                 # Установить pre-commit/pre-push в Git-репозитории
make pre-commit
```

Pre-commit проверяет Ruff и mypy; pre-push запускает изолированные тесты и
строгую сборку документации. CI проверяет Python 3.12.
[Тестирование](docs/guides/testing.md).

## Документация и changelog

Русские Google-докстринги с типами собираются MkDocs Material/mkdocstrings.
`docs/` содержит исходники; `.build/docs/` — генерируемый HTML вне Git и образа.

```bash
make docs
make docs-serve             # http://127.0.0.1:8001
```
