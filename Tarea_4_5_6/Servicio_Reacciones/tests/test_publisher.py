import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aio_pika

from app.core.config import settings
from app.schemas.event import ReactionEvent, ReactionEventData
from app.services.event_producer import RabbitMQEventProducer


class PublisherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = patch.multiple(
            settings, EVENTS_ENABLED=True, EVENT_PUBLISH_RETRIES=1,
            EVENT_PUBLISH_RETRY_DELAY_SECONDS=0, EVENT_TIMEOUT_SECONDS=0.05,
        )
        self.config.start()
        self.addCleanup(self.config.stop)
        self.producer = RabbitMQEventProducer()
        self.event = ReactionEvent(event_type="REACTION_CREATED", data=ReactionEventData(
            id="reaction", message_id="msg", user_id="usr", reaction_type="like",
        ))
        self.exchange = SimpleNamespace(publish=AsyncMock(return_value=True))
        self.queue = SimpleNamespace(bind=AsyncMock())
        self.channel = SimpleNamespace(
            is_closed=False, declare_exchange=AsyncMock(return_value=self.exchange),
            declare_queue=AsyncMock(return_value=self.queue),
        )
        connected = asyncio.Event()
        connected.set()
        self.connection = SimpleNamespace(
            is_closed=False, connected=connected,
            channel=AsyncMock(return_value=self.channel), close=AsyncMock(),
        )
        self.connect = patch("aio_pika.connect_robust", new=AsyncMock(return_value=self.connection))
        self.connect.start()
        self.addCleanup(self.connect.stop)
        self.addAsyncCleanup(self.producer.close)

    async def test_publish_confirms_persistent_message_to_durable_queue(self):
        self.assertTrue(await self.producer.publish(self.event))
        self.connection.channel.assert_awaited_once_with(publisher_confirms=True, on_return_raises=True)
        self.channel.declare_queue.assert_awaited_once_with(settings.EVENT_QUEUE, durable=True)
        self.queue.bind.assert_awaited_once_with(self.exchange, routing_key=f"{settings.EVENT_ROUTING_KEY_PREFIX}.#")
        call = self.exchange.publish.call_args
        message = call.args[0]
        self.assertEqual(message.message_id, self.event.event_id)
        self.assertEqual(message.delivery_mode, aio_pika.DeliveryMode.PERSISTENT)
        self.assertEqual(json.loads(message.body)["event_id"], self.event.event_id)
        self.assertTrue(call.kwargs["mandatory"])

    async def test_unroutable_or_failed_publish_remains_retryable(self):
        self.exchange.publish.side_effect = RuntimeError("unroutable")
        self.assertFalse(await self.producer.publish(self.event))
        self.assertFalse(self.producer.is_connected)

    async def test_connect_timeout_is_bounded(self):
        async def stalled(*args, **kwargs):
            await asyncio.sleep(10)
        with patch("aio_pika.connect_robust", new=stalled):
            self.assertFalse(await asyncio.wait_for(self.producer.publish(self.event), 0.5))

    async def test_publish_timeout_is_bounded(self):
        async def stalled(*args, **kwargs):
            await asyncio.sleep(10)
        self.exchange.publish.side_effect = stalled
        self.assertFalse(await asyncio.wait_for(self.producer.publish(self.event), 0.5))

    async def test_retry_reuses_event_identity(self):
        with patch.object(settings, "EVENT_PUBLISH_RETRIES", 2):
            self.exchange.publish.side_effect = [RuntimeError("temporary failure"), True]
            self.assertTrue(await self.producer.publish(self.event))
        ids = [call.args[0].message_id for call in self.exchange.publish.call_args_list]
        self.assertEqual(ids, [self.event.event_id, self.event.event_id])
