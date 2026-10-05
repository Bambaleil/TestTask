"""Модели SQLAlchemy для платежей и транзакционного Outbox."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from payment_service.core.contracts import JsonValue
from payment_service.core.db.models import Base
from payment_service.core.utils.time import utcnow
from payment_service.modules.payments.domain.constants import PaymentStatus


class PaymentRecord(Base):
    """Платёж с уникальным ключом запроса и сохранённым результатом шлюза."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("currency IN ('RUB', 'USD', 'EUR')", name="ck_payments_currency"),
        CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name="ck_payments_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, JsonValue]] = mapped_column(
        "metadata", JSON().with_variant(JSONB(), "postgresql"), default=dict
    )
    status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PENDING)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    webhook_url: Mapped[str] = mapped_column(String(2048))
    webhook_event_id: Mapped[UUID] = mapped_column(Uuid, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class OutboxRecord(Base):
    """Событие, которое публикуется после фиксации транзакции платежа."""

    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_pending", "published_at", "available_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id"))
    topic: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
