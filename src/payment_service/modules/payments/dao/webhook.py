"""HTTP-адаптер доставки платёжных уведомлений."""

from uuid import UUID

import httpx

from payment_service.modules.payments.domain.events import WebhookPayload


class HttpWebhookSender:
    """Адаптер HTTPX с таймаутом и проверкой кода HTTP-ответа."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Получает общий HTTP-клиент с пулом соединений."""
        self.client = client

    async def send(self, url: str, payload: WebhookPayload) -> None:
        """Отправляет результат платежа с неизменным ключом дедупликации.

        Args:
            url: Адрес получателя уведомления.
            payload: Сохранённый результат со стабильным event_id.

        Raises:
            httpx.HTTPStatusError: Получатель вернул код вне диапазона 2xx.
            httpx.RequestError: Сеть или таймаут помешали получить ответ.
        """
        event_id: UUID = payload.event_id
        response = await self.client.post(
            url,
            json=payload.as_payload(),
            headers={"Idempotency-Key": str(event_id), "X-Webhook-Event-ID": str(event_id)},
        )
        response.raise_for_status()
