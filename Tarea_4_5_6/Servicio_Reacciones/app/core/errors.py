import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.schemas.error import ValidationIssue

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "application_error",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class ResourceNotFoundError(AppError):
    def __init__(self, message: str, *, code: str = "resource_not_found", details: Any | None = None):
        super().__init__(
            message,
            code=code,
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class ConflictError(AppError):
    def __init__(self, message: str, *, code: str = "conflict", details: Any | None = None):
        super().__init__(
            message,
            code=code,
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class ExternalServiceError(AppError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "external_service_unavailable",
        status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
        details: Any | None = None,
    ):
        super().__init__(message, code=code, status_code=status_code, details=details)


class EventPublishError(ExternalServiceError):
    def __init__(self, message: str, *, details: Any | None = None):
        super().__init__(message, code="event_publish_failed", details=details)


def build_error_payload(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_payload(exc.code, exc.message, exc.details),
    )


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    details = None if isinstance(exc.detail, str) else exc.detail
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_payload("http_error", message, details),
        headers=exc.headers,
    )


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_error_payload(
            "validation_error",
            "Request validation failed",
            [ValidationIssue.model_validate(error).model_dump(mode="json") for error in exc.errors()],
        ),
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=build_error_payload("database_error", "Database operation failed"),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=build_error_payload("internal_error", "Internal server error"),
    )
