.PHONY: install lint format typecheck test integration check run-api run-consumer migrate docs docs-serve hooks pre-commit observability local-up local-down local-logs local-status docker-test

LOCAL_COMPOSE = docker compose --env-file deploy/local/.env -f deploy/local/compose.yaml
OBSERVABILITY_COMPOSE = $(LOCAL_COMPOSE) -f deploy/local/compose.observability.yaml

install:
	uv sync --frozen
lint:
	uv run --frozen ruff check .
	uv run --frozen ruff format --check .
format:
	uv run --frozen ruff check --fix .
	uv run --frozen ruff format .
typecheck:
	uv run --frozen mypy
test:
	uv run --frozen pytest -m 'not integration' --cov --cov-report=term-missing
integration:
	uv run --frozen pytest -m integration -v
check: lint typecheck test
run-api:
	uv run --frozen --env-file .env payment-api
run-consumer:
	uv run --frozen --env-file .env payment-worker
migrate:
	uv run --frozen --env-file .env alembic upgrade head

docs:
	uv run --frozen --group docs mkdocs build --strict
docs-serve:
	uv run --frozen --group docs mkdocs serve -a 127.0.0.1:8001

hooks:
	uv run --frozen pre-commit install
pre-commit:
	uv run --frozen pre-commit run --all-files
observability:
	$(OBSERVABILITY_COMPOSE) up -d --build
local-up:
	$(LOCAL_COMPOSE) up -d --build
local-down:
	$(OBSERVABILITY_COMPOSE) down
local-logs:
	$(LOCAL_COMPOSE) logs -f api consumer
local-status:
	$(OBSERVABILITY_COMPOSE) ps
docker-test:
	$(LOCAL_COMPOSE) --profile test run --build --rm tests pytest --cov --cov-report=term-missing
