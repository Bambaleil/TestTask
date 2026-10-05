"""Создание таблиц payments и outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создать платежи, события и индекс для опроса Outbox."""
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("webhook_url", sa.String(2048), nullable=False),
        sa.Column("webhook_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')", name="ck_payments_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_pending", "outbox", ["published_at", "available_at"])


def downgrade() -> None:
    """Удалить созданные таблицы в порядке зависимостей."""
    op.drop_index("ix_outbox_pending", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("payments")
