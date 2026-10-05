# Быстрый запуск и примеры

## Docker

Нужен запущенный Docker с Compose 2.24.4+ (для observability overlay).

```bash
cp deploy/local/.env.example deploy/local/.env
make local-up
make local-status
make local-logs
```

В `deploy/local/.env.example` пример заполнения.
Замените их. `.env`.

- API: `http://localhost:8000`.
- RabbitMQ Management: `http://localhost:15672`; логин/пароль из `deploy/local/.env`.
- Платёжные маршруты, `/docs` и `/openapi.json` требуют `X-API-Key`.
  `/health/live` и `/health/ready` доступны без ключа.

Остановка с сохранением данных:

```bash
make local-down
```

## Примеры API

Создание платежа. Сумму лучше передавать строкой: она хранится в `NUMERIC(18, 2)`
и не проходит через двоичную арифметику float.

```bash
curl -i -X POST http://localhost:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-development-api-key-change-me' \
  -H 'Idempotency-Key: order-42' \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Оплата заказа 42",
    "metadata": {"order_id": "42"},
    "webhook_url": "https://merchant.example/webhooks/payments"
  }'
```

Ответ: `202 Accepted`.

```json
{
  "payment_id": "389ce875-f76d-49e1-b2c0-f1895084d4d5",
  "status": "pending",
  "created_at": "2026-10-03T10:00:00Z"
}
```

Получение платежа:

```bash
curl http://localhost:8000/api/v1/payments/PAYMENT_ID \
  -H 'X-API-Key: local-development-api-key-change-me'
```

Детальный ответ содержит `payment_id`, `amount`, `currency`, `description`,
`metadata`, `status`, `idempotency_key`, `webhook_url`, `created_at`, `processed_at`,
`webhook_delivered_at` и `last_error`. Денежные суммы сериализуются строками,
временные метки PostgreSQL — с часовым поясом UTC.

| Ситуация | HTTP-код |
| --- | --- |
| Новый платёж или повтор идентичного запроса с тем же ключом | 202 |
| Тот же ключ с другими данными | 409 |
| Отсутствует или неверен API-ключ | 401 |
| Платёж отсутствует | 404 |
| Некорректный UUID, сумма, валюта, URL или заголовок идемпотентности | 422 |

Поддерживаются RUB, USD, EUR. Сумма положительная, до 16 цифр до запятой и двух
после неё. `Idempotency-Key` — от 1 до 255 символов без пробельных символов.
`description` — от 1 до 1000 символов. Метаданные — произвольный JSON-объект.
Неизвестные поля запроса и нечисловые значения NaN/Infinity в метаданных отклоняются. При сравнении запросов нормализуются сумма,
URL и порядок ключей JSON. Повтор после завершения обработки возвращает текущий
статус того же платежа.

