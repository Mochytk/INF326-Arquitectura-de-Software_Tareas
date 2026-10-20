# Esquemas y contratos

## HTTP

Los modelos de entrada y salida estan en `app/schemas/`. Se pueden consultar
en Swagger (`/docs`, seccion Schemas), ReDoc (`/redoc`) y `/openapi.json` con la
API ejecutandose. La copia consultable sin ejecutar Python es
[openapi.json](openapi.json).

| Modelo | Campos principales | Uso |
| --- | --- | --- |
| ReactionCreate | message_id, user_id, reaction_type | POST |
| ReactionResponse | anteriores, id, created_at | Respuesta de creacion |
| ReactionSummary | reaction_type, count | Conteo agrupado |
| MessageReactionsResponse | message_id, total_reactions, summary, reactions | Consulta por mensaje |
| ErrorResponse | error.code, error.message, error.details | Errores HTTP |
| ValidationIssue | type, loc, msg | Detalle de errores 422 |
| HealthResponse | status, version, database, events_enabled, rabbitmq_connected, outbox_pending | Salud |

Los identificadores de mensaje y usuario admiten entre 1 y 128 caracteres tras
quitar espacios exteriores. El tipo de reaccion admite entre 1 y 32 caracteres,
se normaliza a minusculas y debe cumplir `^[a-z0-9_-]+$`. Se usan nombres como
`like` o `heart`, no caracteres emoji.

## Errores

Todas las respuestas de error generadas por esta aplicacion usan esta envoltura:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      {
        "type": "string_pattern_mismatch",
        "loc": ["body", "reaction_type"],
        "msg": "String should match pattern '^[a-z0-9_-]+$'"
      }
    ]
  }
}
```

`details` es opcional. Los errores de validacion muestran tipo, ubicacion y
mensaje; se omiten objetos de excepcion e inputs sin procesar para garantizar
que la respuesta pueda serializarse.

| HTTP | Situacion |
| --- | --- |
| 400 | Cuerpo que no puede interpretarse |
| 404 | Mensaje, usuario, reaccion o ruta inexistente |
| 405 | Metodo no permitido; se conserva la cabecera Allow |
| 409 | Reaccion duplicada |
| 422 | JSON o campos invalidos |
| 500 | Fallo de base de datos o error inesperado |
| 502 | Respuesta inesperada de validacion externa |
| 503 | Dependencia requerida no disponible |

## Eventos

El modelo `ReactionEvent` esta en `app/schemas/event.py`. Su JSON Schema esta en
[reaction-event.schema.json](reaction-event.schema.json).

```json
{
  "event_id": "f40ca1e8-ef65-4b10-94ab-30ec46b83b18",
  "event_type": "REACTION_CREATED",
  "timestamp": "2026-10-17T12:00:00Z",
  "data": {
    "id": "d6454bb3-b9b7-4cd6-b627-97534dbd8f75",
    "message_id": "msg-1234",
    "user_id": "usr-5678",
    "reaction_type": "like"
  }
}
```

El otro tipo permitido es `REACTION_DELETED`. Las routing keys predeterminadas
son `reaction.reaction_created` y `reaction.reaction_deleted`. El identificador
AMQP `message_id` coincide con `event_id` y se conserva en los reintentos.

## Regenerar contratos

Desde la raiz, con las dependencias instaladas:

```bash
python scripts/export_schemas.py
```

El comando genera OpenAPI, JSON Schema de eventos y DDL de SQLite desde los
modelos vigentes. No conecta con RabbitMQ ni modifica bases de datos.
