"""Ошибки общих механизмов хранения и бизнес-операций."""


class BusinessError(Exception):
    """Базовая ошибка предметной области, не связанная с HTTP."""


class PersistenceConflictError(Exception):
    """Ограничение целостности БД запрещает сохранить запись."""


class RecordNotFoundError(Exception):
    """Изменяемая запись исчезла из хранилища."""
