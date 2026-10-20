# Servicio de Reacciones

Una unica API REST con FastAPI para crear, consultar y eliminar reacciones a
mensajes de chat. Version actual: **1.0.1**, definida en [VERSION](VERSION).

## Ejecutar

```bash
docker compose up --build
```

Compose levanta la API `reaction-service` y su broker RabbitMQ. La API utiliza
SQLite con persistencia en un volumen. Los eventos pendientes se guardan en la
misma base y se reintentan desde una tarea interna de FastAPI.

- API: <http://localhost:8000>
- Swagger y esquemas: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- RabbitMQ Management: <http://localhost:15672> (desarrollo: `reactions/reactions_dev`).

## Endpoints

- `GET /health`
- `POST /api/v1/reactions`
- `GET /api/v1/messages/{message_id}/reactions`
- `DELETE /api/v1/reactions/{reaction_id}`

## Documentacion

- [Configuracion, errores y ejecucion local](README-ReactionService.md).
- [Arquitectura y modelo de datos](docs/ARQUITECTURA.md).
- [Esquemas y contratos HTTP, eventos y SQL](docs/ESQUEMAS.md).
- [Historial de versiones](CHANGELOG.md).
- [Arreglos, verificaciones y cautelas](INFORME_ARREGLOS.txt).

## Pruebas y contratos

```bash
python -m unittest discover -v
python scripts/export_schemas.py
```

Las pruebas automatizadas usan bases temporales y conexiones externas simuladas.
Las comprobaciones con contenedores se describen en la guia detallada.
