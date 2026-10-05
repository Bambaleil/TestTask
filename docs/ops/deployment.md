# Развёртывание и настройки

## Ответственность приложения и платформы

Образ содержит API, consumer и миграции. PostgreSQL, RabbitMQ, ingress/TLS,
хранилище секретов, сбор логов и Grafana предоставляются платформой.
API и consumer запускаются отдельными процессами; реплики и лимиты ресурсов
задаёт инфраструктура. Одна реплика consumer одновременно обрабатывает одно
сообщение согласно prefetch; дополнительные реплики масштабируют обработку.

Шлюз `SimulatedGateway` остаётся эмулятором согласно тестовому заданию.
Для реального провайдера требуется адаптер порта `PaymentGateway`, использующий
UUID платежа как стабильный ключ внешней идемпотентности.

## Сборка и выпуск

```bash
docker build --target production -t payment-service:0.4.0 .
```

Контекст сборки исключает конфигурации стенда, `.env`, документацию и её HTML.
Зависимости установлены из `uv.lock`, образ запускается от UID/GID 10001.
Выпуск должен использовать неизменяемый тег или digest, а секреты поступают
через окружение процессов или Secret-механизм выбранного оркестратора.

Пример для хоста с внешними PostgreSQL и RabbitMQ:

```bash
# Передайте PAYMENT_IMAGE, DATABASE_URL, API_KEY, RABBITMQ_URL через окружение.
docker compose -f deploy/production/compose.yaml --profile migration run --rm migrate
docker compose -f deploy/production/compose.yaml up -d
```

Миграция выполняется отдельным шагом до обновления API/consumer. При её ошибке
процедура выпуска останавливается; следующий шаг выполняется только после успеха.
Миграционному процессу нужен только DSN БД. Автоматический rollback схемы не
предусмотрен: миграции изменяют данные, поэтому совместимость проверяется
на staging и резервной копии перед выпуском.

Production Compose содержит только процессы приложения. Файловая система
контейнеров доступна для чтения; временные файлы — в `/tmp` (tmpfs). Capabilities
удалены, включён `no-new-privileges`. API опубликован на localhost для внешнего
reverse proxy; порт состояния consumer остаётся внутри сети. Сбор stdout и
ротацию журналов настраивает Docker daemon или платформенный агент.


## Настройки процессов

| Процесс | Обязательные параметры | Класс |
| --- | --- | --- |
| API | `API_KEY` (минимум 16 символов), `DATABASE_URL` | `ApiSettings` |
| Consumer | `DATABASE_URL`, `RABBITMQ_URL` | `WorkerSettings` |
| Миграции | `DATABASE_URL` | `DatabaseSettings` |

| Параметр | Значение по умолчанию |
| --- | --- |
| `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` | 10 / 10 подключений на процесс |
| `DATABASE_POOL_TIMEOUT` | 5 секунд ожидания подключения из пула |
| `LOG_LEVEL` | INFO |
| `OUTBOX_POLL_INTERVAL` / `OUTBOX_BATCH_SIZE` | 0.5 секунды / 50 событий |
| `PUBLISH_TIMEOUT` / `WEBHOOK_TIMEOUT` | 5 / 5 секунд |
| `RETRY_BASE_DELAY` | 2 секунды |
| `WORKER_HEALTH_PORT` | 8081 |

Размер пула учитывается для каждой реплики: верхняя граница подключений равна
числу процессов, умноженному на `pool_size + max_overflow`. 
Лимит согласуется с доступным бюджетом PostgreSQL. DSN использует `postgresql+asyncpg`;
специальные символы логина/пароля URL-кодируются. 
Worker поддерживает AMQP/AMQPS через RabbitMQ-адаптер. 
Настройки не включают адреса Loki, путь файла журналов или пароль Grafana.

## Запуск на хосте для разработки

`.env` загружается явно инструментом запуска. Для Python на хосте DSN должен
указывать на доступные хосту адреса, например `localhost`.

```bash
uv sync --frozen
uv run --frozen --env-file .env alembic upgrade head
uv run --frozen --env-file .env payment-api
# В другом терминале:
uv run --frozen --env-file .env payment-worker
```

[Быстрый запуск](../guides/quickstart.md) описывает стенд Docker,
[логи и healthcheck](observability.md) — контракт наблюдаемости.
