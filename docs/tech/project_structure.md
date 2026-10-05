# Структура проекта

## Приложение, окружения и результаты сборки

```text
src/payment_service/                    # Код приложения
migrations/                             # Изменения схемы БД
tests/                                  # Изолированные и интеграционные тесты
docs/                                   # Исходники документации
deploy/
├── local/
│   ├── compose.yaml                    # Локальный PostgreSQL, RabbitMQ и сервис
│   ├── compose.observability.yaml       # Опциональный стек наблюдаемости
│   ├── .env.example                    # Параметры локального стенда
│   └── observability/                  # Конфигурации и панели Grafana/Loki/Alloy
└── production/compose.yaml              # Процессы с внешними зависимостями
.build/docs/                            # Генерируемый HTML, исключён из Git
```

## Python-пакет

```text
src/payment_service/
├── server.py                    # HTTP-приложение и его жизненный цикл
├── worker.py                    # Consumer и его жизненный цикл
├── container.py                 # Связывание портов с адаптерами
├── schema.py                    # Регистрация ORM-таблиц для Alembic
├── core/                        # Общее ядро
│   ├── settings.py              # Настройки из окружения
│   ├── logging.py               # JSON stdout без привязки к хранилищу логов
│   ├── health.py                # Проверки состояния и готовности
│   ├── contracts.py             # Общий JSON-тип
│   ├── routes.py                # Системные HTTP-маршруты
│   ├── auth/dependencies.py     # Статический API-ключ
│   ├── errors/                  # Общие ошибки и HTTP-преобразование
│   ├── db/                      # Base, пул, порт и реализация Unit of Work
│   ├── events/                  # Общий Outbox и RabbitMQ publisher
│   └── utils/                   # UTC и экспоненциальная задержка
└── modules/payments/            # Предметная область платежей
    ├── module.py                # Сборка и подключение модуля
    ├── views.py                 # HTTP-адаптер
    ├── dependencies.py          # Получение repository из приложения
    ├── repository.py            # Создание, чтение, идемпотентность
    ├── processing.py            # Оплата, уведомление, retry/DLQ
    ├── domain/                  # Сущности, события, ошибки и порты
    ├── dao/
    │   ├── models.py            # Валидируемые DTO API и сообщения
    │   ├── tables.py            # SQLAlchemy records: payments, outbox
    │   ├── sqlalchemy.py        # SQL и преобразование records ↔ entities
    │   ├── unit_of_work.py      # Согласованные DAO одной транзакции
    │   ├── gateway.py           # Эмулятор внешнего провайдера
    │   └── webhook.py           # HTTPX-адаптер уведомлений
    └── handlers/
        ├── rabbitmq.py          # Валидация события, ACK/NACK/reject
        └── topology.py          # Платёжные очереди, exchanges и DLQ
```
