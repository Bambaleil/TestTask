"""Общие типы сериализуемых данных без зависимости от транспорта."""

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
