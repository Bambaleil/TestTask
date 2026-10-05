FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 payments && useradd --uid 10001 --gid payments --no-create-home payments
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
USER payments
CMD ["payment-api"]

FROM builder AS test
RUN uv sync --frozen --no-editable
COPY tests ./tests
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH"
CMD ["pytest", "-m", "integration", "-v"]

FROM runtime AS production
