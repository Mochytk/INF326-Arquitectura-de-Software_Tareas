"""REST endpoints for chat reactions."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ConflictError, ResourceNotFoundError
from app.models.reaction import Reaction
from app.schemas.event import ReactionEventData
from app.schemas.reaction import (
    MessageReactionsResponse,
    ReactionCreate,
    ReactionResponse,
    ReactionSummary,
)
from app.services.event_producer import require_event_broker
from app.services.external import validate_message_exists, validate_user_exists
from app.services.outbox import enqueue_reaction_event

router = APIRouter()


@router.post(
    "/reactions", response_model=ReactionResponse, status_code=status.HTTP_201_CREATED,
    summary="Agregar una reaccion",
)
async def add_reaction(reaction_in: ReactionCreate, db: AsyncSession = Depends(get_db)):
    if not await validate_message_exists(reaction_in.message_id):
        raise ResourceNotFoundError("Message not found", code="message_not_found")
    if not await validate_user_exists(reaction_in.user_id):
        raise ResourceNotFoundError("User not found", code="user_not_found")

    result = await db.execute(select(Reaction).where(
        Reaction.message_id == reaction_in.message_id,
        Reaction.user_id == reaction_in.user_id,
        Reaction.reaction_type == reaction_in.reaction_type,
    ))
    if result.scalars().first():
        raise ConflictError("User already reacted with this type", code="duplicate_reaction")

    await require_event_broker()
    reaction = Reaction(**reaction_in.model_dump())
    db.add(reaction)
    try:
        await db.flush()
        response = ReactionResponse.model_validate(reaction)
        enqueue_reaction_event(db, "REACTION_CREATED", ReactionEventData(
            id=reaction.id, **reaction_in.model_dump()
        ))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("User already reacted with this type", code="duplicate_reaction") from exc

    # No broker calls or database refreshes after a successful commit.
    return response


@router.get(
    "/messages/{message_id}/reactions", response_model=MessageReactionsResponse,
    summary="Consultar las reacciones de un mensaje",
)
async def get_message_reactions(message_id: str, db: AsyncSession = Depends(get_db)):
    if not await validate_message_exists(message_id):
        raise ResourceNotFoundError("Message not found", code="message_not_found")

    result = await db.execute(select(Reaction).where(Reaction.message_id == message_id))
    reactions = result.scalars().all()
    summary_result = await db.execute(
        select(Reaction.reaction_type, func.count(Reaction.id))
        .where(Reaction.message_id == message_id)
        .group_by(Reaction.reaction_type)
    )
    return MessageReactionsResponse(
        message_id=message_id,
        total_reactions=len(reactions),
        summary=[
            ReactionSummary(reaction_type=row[0], count=row[1])
            for row in summary_result.all()
        ],
        reactions=reactions,
    )


@router.delete(
    "/reactions/{reaction_id}", status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una reaccion",
)
async def delete_reaction(reaction_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reaction).where(Reaction.id == reaction_id))
    reaction = result.scalars().first()
    if not reaction:
        raise ResourceNotFoundError("Reaction not found", code="reaction_not_found")

    await require_event_broker()
    event_data = ReactionEventData(
        id=reaction.id, message_id=reaction.message_id,
        user_id=reaction.user_id, reaction_type=reaction.reaction_type,
    )
    await db.delete(reaction)
    enqueue_reaction_event(db, "REACTION_DELETED", event_data)
    await db.commit()
    return None
