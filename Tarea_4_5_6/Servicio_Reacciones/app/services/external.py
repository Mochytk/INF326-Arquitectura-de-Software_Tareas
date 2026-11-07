"""
Servicios y Clientes Externos.

Aquí se define toda la lógica de conexión (clientes HTTP) hacia otros microservicios.
En este caso particular, se simula la consulta hacia los servicios de Mensajes y Usuarios.

Modifica este archivo si:
- Tienes las URLs reales de los servicios externos y necesitas "descomentar" la lógica
  que usa `httpx`.
- Necesitas consultar otra API externa o de terceros.
"""

import httpx
from app.core.config import settings
from app.core.errors import ExternalServiceError
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

async def _validate_resource_exists(service_name: str, base_url: str, resource_id: str) -> bool:
    if not settings.EXTERNAL_VALIDATION_ENABLED:
        logger.info("Validando %s %s en modo simulado", service_name, resource_id)
        return resource_id != settings.VALIDATION_SIMULATED_NOT_FOUND_ID

    url = f"{base_url.rstrip('/')}/{quote(resource_id, safe='')}"
    timeout = httpx.Timeout(settings.VALIDATION_TIMEOUT_SECONDS)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ExternalServiceError(
            f"{service_name} service timed out",
            details={"url": url, "timeout_seconds": settings.VALIDATION_TIMEOUT_SECONDS},
        ) from exc
    except httpx.HTTPError as exc:
        raise ExternalServiceError(
            f"{service_name} service unavailable",
            details={"url": url, "error": str(exc)},
        ) from exc

    if response.status_code == 404:
        return False
    if 200 <= response.status_code < 300:
        return True
    if response.status_code >= 500:
        raise ExternalServiceError(
            f"{service_name} service returned an upstream error",
            details={"url": url, "status_code": response.status_code},
        )

    raise ExternalServiceError(
        f"{service_name} service returned an unexpected response",
        code="external_validation_failed",
        status_code=502,
        details={"url": url, "status_code": response.status_code, "body": response.text[:500]},
    )


async def validate_message_exists(message_id: str, channel_id: str | None = None) -> bool:
    """Valida un mensaje en el canal del chat base, o simula validación en local.

    MESSAGES_SERVICE_URL debe apuntar al prefijo /api/v1/channels.
    La API base no expone GET /api/v1/messages/{message_id}.
    """
    if not settings.EXTERNAL_VALIDATION_ENABLED:
        logger.info("Validando Messages %s en modo simulado", message_id)
        return message_id != settings.VALIDATION_SIMULATED_NOT_FOUND_ID

    if not channel_id:
        # Capa de API también impide que falte en modo real.
        raise ExternalServiceError(
            "channel_id is required to validate a message",
            code="channel_id_required", status_code=422,
        )

    url = f"{settings.MESSAGES_SERVICE_URL.rstrip('/')}/{quote(channel_id, safe='')}/messages"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.VALIDATION_TIMEOUT_SECONDS)) as client:
            response = await client.get(url)
    except httpx.TimeoutException as exc:
        raise ExternalServiceError("Messages service timed out") from exc
    except httpx.HTTPError as exc:
        raise ExternalServiceError("Messages service unavailable") from exc

    if response.status_code == 404:
        return False
    if response.status_code >= 500:
        raise ExternalServiceError("Messages service returned an upstream error")
    if not 200 <= response.status_code < 300:
        raise ExternalServiceError(
            "Messages service returned an unexpected response",
            code="external_validation_failed", status_code=502,
        )

    try:
        messages = response.json()
    except ValueError as exc:
        raise ExternalServiceError(
            "Messages service returned invalid JSON",
            code="external_validation_failed", status_code=502,
        ) from exc

    # El contrato observado en Kubernetes es una lista de mensajes.
    if not isinstance(messages, list) or any(not isinstance(m, dict) for m in messages):
        raise ExternalServiceError(
            "Messages service returned an unexpected schema",
            code="external_validation_failed", status_code=502,
        )

    return any(
        str(message.get("id")) == message_id
        and str(message.get("channel_id")) == channel_id
        for message in messages
    )


async def validate_user_exists(user_id: str) -> bool:
    """Valida con GET /api/v1/users/{user_id} cuando se activa el modo real."""
    return await _validate_resource_exists("Users", settings.USERS_SERVICE_URL, user_id)
