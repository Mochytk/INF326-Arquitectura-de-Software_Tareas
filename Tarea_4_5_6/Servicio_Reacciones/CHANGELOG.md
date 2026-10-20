# Historial de cambios

## 1.0.1 - 2026-10-17

- Corregida la serializacion de errores de validacion: entradas invalidas devuelven 422.
- Unificado el formato de errores 400, 404, 405, 409, 422, 500, 502 y 503.
- Reaccion y evento se guardan atomicamente mediante una outbox persistente.
- El modo de broker obligatorio rechaza antes de escribir cuando no hay conexion.
- Publicacion con limites de tiempo, confirmaciones, reintentos e identificador estable.
- Exchange y cola durables; credenciales de desarrollo para conexion entre contenedores.
- Health check real de base de datos y disponibilidad del broker requerido.
- Esquemas HTTP, de eventos y SQL exportables, con diagramas de arquitectura y datos.
- Version centralizada en VERSION, compartida por FastAPI y la imagen Docker.
- Pruebas automatizadas para los errores y la recuperacion del servicio.

## 1.0.0 - Estado anterior

- API REST para crear, consultar y eliminar reacciones.
- Validacion externa configurable y publicacion directa a RabbitMQ.
- Esta numeracion estaba declarada en FastAPI, sin una entrega Git etiquetada.
