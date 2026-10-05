# Тестирование и проверки

## Команды

```bash
make check                    # Ruff, форматирование, mypy, быстрые тесты + coverage
make format                   # Исправить lint и форматирование
make test                     # Быстрые тесты без внешних сервисов
```

Интеграционные тесты без установки Python-зависимостей на хосте:

```bash
docker compose --env-file deploy/local/.env -f deploy/local/compose.yaml --profile test run --build --rm tests
```

Все тесты и общий отчёт покрытия в контейнере:

```bash
make docker-test
```

Или интеграционные тесты из локального окружения после запуска инфраструктуры:

```bash
TEST_DATABASE_URL='postgresql+asyncpg://payments:local-postgres-password@localhost:5432/payments' \
TEST_RABBITMQ_URL='amqp://payments:local-rabbit-password@localhost:5672/' \
uv run --frozen pytest -m integration -v
```

## Настройки тестового окружения

Основные параметры окружения: `API_KEY`, `DATABASE_URL`, `RABBITMQ_URL`,
`OUTBOX_POLL_INTERVAL` (0.5), `OUTBOX_BATCH_SIZE` (50), `PUBLISH_TIMEOUT` (5),
`WEBHOOK_TIMEOUT` (5), `RETRY_BASE_DELAY` (2), `LOG_LEVEL` (INFO).
API-ключ обязателен и должен содержать минимум 16 символов.

Использованные контракты FastStream: [публикация RabbitBroker](https://faststream.ag2.ai/latest/api/faststream/rabbit/RabbitBroker/)
и [ручное подтверждение сообщений](https://faststream.ag2.ai/latest/getting-started/acknowledgement/).
