from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.reaction import ReactionBase


class ReactionEventData(ReactionBase):
    id: str


class ReactionEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: Literal["REACTION_CREATED", "REACTION_DELETED"]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: ReactionEventData
