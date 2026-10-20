from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok"]
    events_enabled: bool
    rabbitmq_connected: bool
    outbox_pending: int = Field(ge=0)
