"""Базовая декларативная модель; таблицы регистрируются в модулях."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Объединяет метаданные подключённых доменных модулей."""
