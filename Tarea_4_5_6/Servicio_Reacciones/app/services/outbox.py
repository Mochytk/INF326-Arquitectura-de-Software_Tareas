import asyncio
import logging
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.outbox import OutboxEvent
from app.schemas.event import ReactionEvent, ReactionEventData
from app.services.event_producer import event_producer

logger = logging.getLogger(__name__)


def enqueue_reaction_event(
    db: AsyncSession,
    event_type: Literal["REACTION_CREATED", "REACTION_DELETED"],
    data: ReactionEventData,
) -> None:
    if not settings.EVENTS_ENABLED:
        return
    event = ReactionEvent(event_type=event_type, data=data)
    db.add(OutboxEvent(
        event_id=event.event_id,
        payload=event.model_dump(mode="json"),
        created_at=event.timestamp,
    ))


async def dispatch_pending_events() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(OutboxEvent)
            .order_by(OutboxEvent.created_at, OutboxEvent.event_id)
            .limit(settings.OUTBOX_BATCH_SIZE)
        )
        pending = [ReactionEvent.model_validate(row.payload) for row in result.scalars()]

    sent = 0
    # Close the read session before waiting for RabbitMQ to avoid holding DB locks.
    for event in pending:
        if not await event_producer.publish(event):
            break
        async with AsyncSessionLocal() as db:
            await db.execute(delete(OutboxEvent).where(OutboxEvent.event_id == event.event_id))
            await db.commit()
        sent += 1
    return sent


async def run_outbox() -> None:
    while True:
        try:
            await event_producer.connect()
            await dispatch_pending_events()
        except Exception:
            logger.exception("Outbox delivery failed; pending events will be retried")
        await asyncio.sleep(settings.OUTBOX_POLL_INTERVAL_SECONDS)
