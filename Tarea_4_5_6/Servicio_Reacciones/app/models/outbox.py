from sqlalchemy import JSON, Column, DateTime, String

from app.core.database import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    event_id = Column(String, primary_key=True)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
