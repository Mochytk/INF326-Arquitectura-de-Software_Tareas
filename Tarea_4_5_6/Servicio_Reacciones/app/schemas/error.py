from typing import Any

from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    type: str
    loc: list[str | int]
    msg: str


class ErrorDetail(BaseModel):
    code: str = Field(examples=["validation_error"])
    message: str = Field(examples=["Request validation failed"])
    details: dict[str, Any] | list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


ERROR_RESPONSES = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        400: "Malformed request",
        404: "Resource or route not found",
        405: "Method not allowed",
        409: "Duplicate reaction",
        422: "Request validation failed",
        500: "Database or internal error",
        502: "Unexpected response from an external service",
        503: "Required dependency unavailable",
    }.items()
}
