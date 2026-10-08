"""Общие типы валидации транспортных схем."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
