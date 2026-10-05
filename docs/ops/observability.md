# Логи и healthcheck

## Локальный стенд Grafana

```bash
cp deploy/local/.env.example deploy/local/.env  # Только при первом запуске
make observability
```

`deploy/local/compose.observability.yaml` дополняет основной локальный Compose.
Конфигурации находятся в `deploy/local/observability/`; в образ приложения они
не входят. Docker пересылает stdout API/consumer своим GELF logging driver в
Alloy; Alloy разбирает JSON и отправляет записи в Loki. Файловых томов приложения
и Docker socket у сборщика нет.

GELF использует UDP и неблокирующий буфер: локальная демонстрация допускает
потерю логов при перегрузке или остановке сборщика. Такой транспорт не задаёт
production-политику аудита. Адрес `LOCAL_GELF_ADDRESS` задаётся со стороны Docker
**daemon**, по умолчанию `udp://127.0.0.1:12201`. Для удалённого daemon потребуется
доступный ему адрес сборщика. Обычный `make local-up` использует стандартный
локальный logging driver Docker и работает без стека Grafana.

Grafana: `http://127.0.0.1:3000`. Логин/пароль из `deploy/local/.env`:
`GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`. Datasource Loki и дашборд

```logql
{job="payments", service="consumer"} | json
{job="payments", level=~"WARNING|ERROR|CRITICAL"} | json
{job="payments"} | json | payment_id="UUID-платежа"
```

Конфигурация использует [Docker GELF driver](https://docs.docker.com/engine/logging/drivers/gelf/)
и [Alloy loki.source.gelf](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.gelf/).

## Состояние процессов

| Маршрут | Успех | Отказ | Проверка |
| --- | --- | --- | --- |
| API `/health/live` | 200 | Недоступен процесс | HTTP-процесс отвечает |
| API `/health/ready` | 200 | 503 | Соединение БД и `SELECT 1` |
| Consumer `/health/live` | 200 | Недоступен процесс | HTTP/event loop отвечает |
| Consumer `/health/ready` | 200 | 503 | БД, соединение RabbitMQ, активная задача Outbox |

В оркестраторе liveness подключается к `/health/live`, readiness — к
`/health/ready`. Недоступная внешняя БД не должна вызывать бесконечные рестарты
через liveness. Docker healthcheck использует readiness; `unhealthy` сам по себе
не перезапускает контейнер.

```bash
curl --fail http://127.0.0.1:8000/health/ready
make local-status
make local-logs
docker compose --env-file deploy/local/.env -f deploy/local/compose.yaml exec consumer python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8081/health/ready').read().decode())"
```

Consumer обслуживает состояние на `WORKER_HEALTH_PORT` (8081), внутри сети
контейнеров. При завершении процессы перестают быть готовыми, worker отменяет
Outbox, завершает broker и освобождает HTTP-клиент и пул БД. При диагностике
локального сборщика смотрите логи `alloy` и готовность Loki `/ready`.
