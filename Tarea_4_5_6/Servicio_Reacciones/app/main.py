"""FastAPI application, dependency readiness and lifecycle."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from app.api.v1.reactions import router as reactions_router
from app.core.config import settings
from app.core.database import Base, engine, get_db
from app.core.errors import (
    AppError,
    EventPublishError,
    ExternalServiceError,
    app_error_handler,
    http_exception_handler,
    sqlalchemy_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.version import VERSION
from app.models.outbox import OutboxEvent
from app.schemas.error import ERROR_RESPONSES
from app.schemas.health import HealthResponse
from app.services.event_producer import (
    close_event_producer,
    connect_event_producer,
    event_producer,
)
from app.services.outbox import run_outbox

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        if settings.EVENTS_ENABLED:
            try:
                await connect_event_producer()
            except EventPublishError:
                logger.warning("Starting with RabbitMQ unavailable; outbox will retry")
            worker = asyncio.create_task(run_outbox(), name="reaction-outbox")
        yield
    finally:
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        await close_event_producer()
        await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API REST para crear, consultar y eliminar reacciones a mensajes.",
    version=VERSION,
    responses=ERROR_RESPONSES,
    lifespan=lifespan,
)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(reactions_router, prefix=settings.API_V1_STR, tags=["Reactions"])


@app.get("/health", tags=["Health"], response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        async with asyncio.timeout(settings.HEALTHCHECK_TIMEOUT_SECONDS):
            await db.execute(text("SELECT 1"))
            pending = await db.scalar(select(func.count()).select_from(OutboxEvent))
    except (SQLAlchemyError, TimeoutError) as exc:
        logger.warning("Database readiness check failed", exc_info=True)
        raise ExternalServiceError(
            "Database is unavailable", code="service_unavailable",
            details={"database": "unavailable"},
        ) from exc

    connected = event_producer.is_connected
    if settings.EVENTS_ENABLED and settings.EVENTS_REQUIRED and not connected:
        raise ExternalServiceError(
            "Required event broker is unavailable", code="service_unavailable",
            details={"database": "ok", "rabbitmq": "unavailable", "outbox_pending": pending},
        )
    degraded = settings.EVENTS_ENABLED and (not connected or pending > 0)
    return HealthResponse(
        status="degraded" if degraded else "ok", version=VERSION, database="ok",
        events_enabled=settings.EVENTS_ENABLED, rabbitmq_connected=connected,
        outbox_pending=pending,
    )
