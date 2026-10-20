"""RabbitMQ publisher with bounded retries and a durable event queue."""

import asyncio
import logging

import aio_pika

from app.core.config import settings
from app.core.errors import EventPublishError
from app.schemas.event import ReactionEvent

logger = logging.getLogger(__name__)


class RabbitMQEventProducer:
    def __init__(self):
        self.connection: aio_pika.abc.AbstractRobustConnection | None = None
        self.channel: aio_pika.abc.AbstractRobustChannel | None = None
        self.exchange: aio_pika.abc.AbstractRobustExchange | None = None
        self._ready = False
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return bool(
            self._ready
            and self.connection
            and not self.connection.is_closed
            and self.connection.connected.is_set()
            and self.channel
            and not self.channel.is_closed
            and self.exchange
        )

    async def _connect_locked(self) -> None:
        if not settings.EVENTS_ENABLED or self.is_connected:
            return
        await self._close_locked()
        try:
            async with asyncio.timeout(settings.EVENT_TIMEOUT_SECONDS):
                self.connection = await aio_pika.connect_robust(
                    settings.EVENT_BROKER_URL,
                    timeout=settings.EVENT_TIMEOUT_SECONDS,
                )
                self.channel = await self.connection.channel(
                    publisher_confirms=True, on_return_raises=True
                )
                self.exchange = await self.channel.declare_exchange(
                    settings.EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await self.channel.declare_queue(settings.EVENT_QUEUE, durable=True)
                await queue.bind(
                    self.exchange, routing_key=f"{settings.EVENT_ROUTING_KEY_PREFIX}.#"
                )
                self._ready = True
            logger.info("Connected to RabbitMQ exchange=%s", settings.EVENT_EXCHANGE)
        except (Exception, asyncio.CancelledError) as exc:
            await self._close_locked()
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.warning("RabbitMQ connection failed: %s", exc)
            raise EventPublishError("RabbitMQ is unavailable") from exc

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_locked()

    async def _close_locked(self) -> None:
        connection = self.connection
        self._ready = False
        self.connection = None
        self.channel = None
        self.exchange = None
        if connection and not connection.is_closed:
            try:
                await asyncio.wait_for(connection.close(), settings.EVENT_TIMEOUT_SECONDS)
            except Exception:
                logger.warning("Could not close RabbitMQ connection cleanly", exc_info=True)

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def publish(self, event: ReactionEvent) -> bool:
        if not settings.EVENTS_ENABLED:
            return False
        routing_key = f"{settings.EVENT_ROUTING_KEY_PREFIX}.{event.event_type.lower()}"
        async with self._lock:
            for attempt in range(1, settings.EVENT_PUBLISH_RETRIES + 1):
                try:
                    await self._connect_locked()
                    async with asyncio.timeout(settings.EVENT_TIMEOUT_SECONDS):
                        await self.exchange.publish(
                            aio_pika.Message(
                                body=event.model_dump_json().encode("utf-8"),
                                message_id=event.event_id,
                                content_type="application/json",
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            ),
                            routing_key=routing_key,
                            mandatory=True,
                            timeout=settings.EVENT_TIMEOUT_SECONDS,
                        )
                    return True
                except Exception:
                    logger.warning(
                        "Event %s delivery failed (%s/%s)",
                        event.event_id, attempt, settings.EVENT_PUBLISH_RETRIES,
                        exc_info=True,
                    )
                    await self._close_locked()
                    if attempt < settings.EVENT_PUBLISH_RETRIES:
                        await asyncio.sleep(settings.EVENT_PUBLISH_RETRY_DELAY_SECONDS)
        return False


event_producer = RabbitMQEventProducer()


async def require_event_broker() -> None:
    if settings.EVENTS_ENABLED and settings.EVENTS_REQUIRED:
        try:
            await asyncio.wait_for(event_producer.connect(), settings.EVENT_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise EventPublishError("RabbitMQ availability check timed out") from exc


async def connect_event_producer() -> None:
    await event_producer.connect()


async def close_event_producer() -> None:
    await event_producer.close()
