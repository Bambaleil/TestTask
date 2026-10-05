"""Эмулятор внешнего платёжного провайдера."""

import asyncio
import random

from payment_service.modules.payments.domain.constants import PaymentStatus
from payment_service.modules.payments.domain.entities import Payment


class SimulatedGateway:
    """Эмуляция шлюза: задержка 2–5 секунд и 90% успешных платежей."""

    async def charge(self, payment: Payment) -> PaymentStatus:
        """Возвращает воспроизводимый исход оплаты для идентификатора платежа.

        Args:
            payment: Платёж, UUID которого задаёт стабильный результат.

        Returns:
            succeeded в 90% исходов или failed в 10%; задержка 2–5 секунд.
        """
        # Фиксированный seed даёт одинаковый ответ после сбоя перед commit.
        # Здесь нет реального списания; настоящий адаптер должен передавать
        # payment.id в idempotency key внешнего провайдера.
        generator = random.Random(payment.id.int)  # noqa: S311
        delay = generator.uniform(2, 5)
        outcome = generator.random()
        await asyncio.sleep(delay)
        return PaymentStatus.SUCCEEDED if outcome < 0.9 else PaymentStatus.FAILED
