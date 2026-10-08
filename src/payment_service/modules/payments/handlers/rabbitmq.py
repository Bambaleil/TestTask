"""Адаптер событий платежа с явными ACK, NACK и reject."""

import asyncio
import json
import logging

from faststream.rabbit import RabbitMessage
from pydantic import ValidationError

from payment_service.modules.payments.domain.exceptions import InvalidEventError
from payment_service.modules.payments.processing import PaymentProcessor
from payment_service.modules.payments.schemas import PaymentEventMessage

logger = logging.getLogger(__name__)


def decode_event(message: RabbitMessage) -> object:
    """Декодирует тело, сохраняя возможность отклонить повреждённый JSON.

    Args:
        message: Входящее RabbitMQ-сообщение с необработанными байтами тела.

    Returns:
        Декодированные данные либо None для повреждённого JSON/UTF-8.
    """
    try:
        decoded: object = json.loads(message.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return decoded


class PaymentMessageHandler:
    """Адаптер обработки событий с явными ACK, NACK и reject."""

    def __init__(self, processor: PaymentProcessor, retry_base_delay: float) -> None:
        """Получает прикладной обработчик и задержку при недоступности БД."""
        self.processor = processor
        self.retry_base_delay = retry_base_delay

    async def process_payment(self, body: object, message: RabbitMessage) -> None:
        """Подтверждает событие после сохранения результата или следующей попытки.

        Невалидное сообщение получает reject без requeue. Ошибка долговечного
        хранения получает NACK с requeue; успешная фиксация — ACK.

        Args:
            body: Декодированное тело, проверяемое транспортной DTO.
            message: Транспортный контекст для ACK, NACK и reject.
        """
        try:
            event = PaymentEventMessage.model_validate(body).to_event()
            await self.processor.process(event)
        except (ValidationError, InvalidEventError):
            logger.warning("invalid_payment_event message_id=%s", message.message_id)
            await message.reject(requeue=False)
        except Exception as error:
            logger.warning("payment_consumer_failed error=%s", type(error).__name__)
            # При сбое БД нельзя ACK: состояние retry не стало долговечным.
            # Пауза ограничивает интенсивность повторной доставки при аварии БД.
            await asyncio.sleep(self.retry_base_delay)
            await message.nack(requeue=True)
        else:
            await message.ack()
