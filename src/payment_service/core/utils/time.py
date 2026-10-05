"""Утилиты времени для хранения и сравнения событий."""

from datetime import UTC, datetime
from typing import overload


def utcnow() -> datetime:
    """Возвращает текущее время с часовым поясом UTC."""
    return datetime.now(UTC)


@overload
def ensure_utc(value: datetime) -> datetime: ...


@overload
def ensure_utc(value: None) -> None: ...


@overload
def ensure_utc(value: datetime | None) -> datetime | None: ...


def ensure_utc(value: datetime | None) -> datetime | None:
    """Восстанавливает UTC для хранилищ, которые возвращают наивные даты.

    Args:
        value: Дата из хранилища или отсутствие даты.

    Returns:
        Дата в UTC; None сохраняется без преобразования.

    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
