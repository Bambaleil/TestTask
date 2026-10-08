# Тестирование и проверки

## Команды

```bash
make check                    # Ruff, форматирование, mypy, быстрые тесты + coverage
make format                   # Исправить lint и форматирование
make test                     # Быстрые тесты без внешних сервисов
```

Интеграционные тесты без установки Python-зависимостей на хосте:

```bash
docker compose --profile test run --build --rm tests
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

## Критические сценарии

Быстрые тесты используют SQLite и подменённые внешние адаптеры. Интеграционные
тесты применяют настоящие миграции PostgreSQL и отдельные очереди RabbitMQ.
Каждый тест получает собственную схему БД и топологию брокера, которые удаляются
после проверки. Отсутствие URL внешних сервисов приводит к пропуску интеграционных
тестов; такой запуск не подтверждает работу PostgreSQL-блокировок или AMQP.

```bash
# Транзакции, отказ доставки и конкуренция на настоящих сервисах
docker compose --profile test run --build --rm tests pytest \
  tests/integration/test_transactions.py tests/integration/test_delivery_failures.py -v
```

В `tests/integration/test_transactions.py` проверяются общая сессия платежа и
Outbox, невидимость незавершённой транзакции, полный rollback при ошибке INSERT,
ошибке commit и отмене, атомарность retry/DLQ и одновременная обработка одного
события. В `test_postgres.py` проверяются конкурентные запросы создания платежа
с одинаковым ключом и `FOR UPDATE SKIP LOCKED`.

В `tests/integration/test_delivery_failures.py` проверяются HTTP 500 через
настоящий HTTPX-адаптер, экспоненциальные задержки, DLQ после третьей попытки,
повторная публикация после RabbitMQ confirm и сбоя commit, настоящий NACK с
повторной доставкой и повтор webhook после успешного HTTP-ответа и сбоя commit.
HTTP-ответы управляются через `httpx.MockTransport`; PostgreSQL и RabbitMQ
работают без подмены. Точки отказа БД вводятся после настоящих INSERT/flush.

Полный запуск `make docker-test` и CI требуют 100% покрытия строк и ветвей кода
приложения. Это дополнительная проверка; процент покрытия сам по себе не
доказывает надёжность. Гарантии подтверждают проверяемые состояния БД,
AMQP-подтверждения и количество внешних вызовов. Перезапуск обработчика
проверяется созданием нового экземпляра с чтением долговечного состояния;
принудительное завершение контейнера или разрыв сети эти тесты не моделируют.
