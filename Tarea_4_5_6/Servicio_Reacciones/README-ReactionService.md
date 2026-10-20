# Guia del Servicio de Reacciones

Version **1.0.1**. Una sola aplicacion FastAPI en `app/`, con RabbitMQ como broker
y SQLite como persistencia. La version que muestran OpenAPI y `/health` se lee
de [VERSION](VERSION); la imagen Docker incluye ese mismo archivo.

## Docker Compose

```bash
docker compose up --build
```

La API se expone en <http://localhost:8000>, Swagger en
<http://localhost:8000/docs>, ReDoc en <http://localhost:8000/redoc> y la consola
RabbitMQ en <http://localhost:15672>.

Las credenciales predeterminadas de desarrollo son `reactions/reactions_dev`.
`RABBITMQ_DEFAULT_USER` y `RABBITMQ_DEFAULT_PASS` configuran el broker y la URL
que recibe la API en Compose. Para credenciales con caracteres reservados de
URL, configura una URL AMQP correctamente escapada. Cambia las credenciales
antes de exponer este entorno fuera de desarrollo.

Si ya existe un volumen RabbitMQ, las variables DEFAULT no modifican sus
usuarios. Configura el usuario y sus permisos en ese broker antes de usarlo con
la API; conserva los datos del volumen.

La API puede arrancar mientras RabbitMQ aun no esta listo. El despachador
reintenta la conexion y conserva los eventos pendientes en el volumen SQLite.

## Python local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
mkdir -p data
uvicorn app.main:app --reload
```

Para probar la API sin RabbitMQ, configura `EVENTS_ENABLED=false` y
`EVENTS_REQUIRED=false`. La URL AMQP local del ejemplo usa `localhost`;
Compose configura automaticamente el nombre interno `rabbitmq`.

## API REST y esquemas

| Metodo | Ruta | Resultado |
| --- | --- | --- |
| GET | /health | Estado y version |
| POST | /api/v1/reactions | Crear una reaccion: 201 |
| GET | /api/v1/messages/{message_id}/reactions | Listado y resumen: 200 |
| DELETE | /api/v1/reactions/{reaction_id} | Eliminar: 204 sin cuerpo |

Ejemplo para crear una reaccion:

```json
{
  "message_id": "msg-1234",
  "user_id": "usr-5678",
  "reaction_type": "like"
}
```

Los modelos, restricciones y contratos estan en [Esquemas](docs/ESQUEMAS.md).
Los diagramas estan en [Arquitectura](docs/ARQUITECTURA.md).
`docs/openapi.json` permite revisar la API sin levantar el servicio.

## Errores

Todos los errores de la aplicacion usan `{"error": {"code": "...", "message": "..."}}`,
con `details` opcional. Los errores de validacion responden 422 y muestran
tipo, ubicacion y mensaje. Rutas inexistentes (404) y metodos no permitidos
(405) usan el mismo formato. Los fallos internos se registran en logs y la
respuesta no incluye trazas de Python.

Los errores 400, 404, 405, 409, 422, 500, 502 y 503 estan descritos en OpenAPI
con el modelo `ErrorResponse`.

## Eventos, transacciones y recuperacion

Con `EVENTS_ENABLED=true`, cada creacion o eliminacion guarda su evento en
`outbox_events` dentro de la misma transaccion de la reaccion. La API devuelve
201 o 204 despues de confirmar la base; no publica a RabbitMQ despues del
commit dentro de la peticion.

El despachador del mismo proceso envia pendientes a un exchange topic durable y
una cola durable. Solo elimina el pendiente tras la confirmacion del broker.
Un fallo de conexion o publicacion conserva el evento para otro intento,
incluidos los reinicios de la API.

`EVENTS_REQUIRED=false` permite escrituras durante una caida del broker.
`EVENTS_REQUIRED=true` exige una conexion antes de modificar datos: si no se
puede comprobar, devuelve 503 y no guarda ni elimina la reaccion. Una caida
posterior al commit conserva el resultado exitoso y deja el evento pendiente.
Esta opcion no promete una transaccion distribuida con RabbitMQ.

La entrega es al menos una vez: los consumidores deben deduplicar por
`event_id`, que coincide con el `message_id` AMQP y se conserva en reintentos.
La cola predeterminada es `reactions.events`; consumidores con sus propias
colas pueden enlazarlas al exchange `reactions` y las routing keys deseadas.

`EVENTS_ENABLED=false` deshabilita el registro y envio de nuevos eventos. Los
pendientes anteriores se conservan hasta volver a habilitar la funcionalidad.

## Salud

`GET /health` consulta la base de datos y los eventos pendientes con un limite
de tiempo. Devuelve 503 si falla esa consulta o el broker obligatorio esta
desconectado. Con broker opcional desconectado o eventos pendientes, devuelve
200 y `status: degraded`. El estado incluye version y cantidad de pendientes.

## Configuracion

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| EXTERNAL_VALIDATION_ENABLED | false | Consultar usuarios y mensajes por HTTP |
| MESSAGES_SERVICE_URL / USERS_SERVICE_URL | Ver .env.example | URLs externas |
| VALIDATION_TIMEOUT_SECONDS | 3 | Limite por consulta HTTP |
| EVENTS_ENABLED | true | Registrar y despachar eventos |
| EVENTS_REQUIRED | false | Exigir conexion antes de escribir |
| EVENT_BROKER_URL | AMQP local | Conexion; Compose configura su propia URL |
| EVENT_EXCHANGE / EVENT_QUEUE | reactions / reactions.events | Exchange y cola |
| EVENT_ROUTING_KEY_PREFIX | reaction | Prefijo de routing keys |
| EVENT_PUBLISH_RETRIES | 3 | Intentos por lote de envio |
| EVENT_PUBLISH_RETRY_DELAY_SECONDS | 0.5 | Pausa entre intentos |
| EVENT_TIMEOUT_SECONDS | 3 | Limite de conexion/publicacion |
| OUTBOX_POLL_INTERVAL_SECONDS | 1 | Pausa entre pasadas del despachador |
| OUTBOX_BATCH_SIZE | 100 | Maximo de eventos por pasada |
| HEALTHCHECK_TIMEOUT_SECONDS | 2 | Limite para la consulta de salud |

Las variables se leen del entorno o de `.env`. En Compose, las opciones
declaradas con interpolacion en `docker-compose.yml` pueden ajustarse desde
`.env`; las demas se agregan en el bloque `environment` si se necesitan.

Los servicios de usuarios y mensajes son externos a este proyecto. Deben
responder 2xx si el recurso existe y 404 si no existe. El modo simulado rechaza
el ID `not-found`. Esta comprobacion valida existencia; la autenticacion y los
permisos de quien llama deben integrarse con la identidad del sistema de chat.

## Versionamiento

`VERSION` es la fuente unica para la version de la aplicacion; `/api/v1`
identifica la familia de endpoints. Los cambios se registran en
[CHANGELOG.md](CHANGELOG.md). Antes de publicar una version, actualiza VERSION,
el changelog y la documentacion, ejecuta las pruebas y regenera los contratos.
Registra el codigo en un commit y etiqueta ese commit como `v1.0.1` para esta
entrega. Una release de GitHub se asocia a esa etiqueta; no se crea por escribir
un numero en el README.

## Pruebas

```bash
python -m unittest discover -v
python scripts/export_schemas.py
```

Los tests usan SQLite temporal y fallos simulados para comprobar validacion,
errores HTTP, disponibilidad, rollback, recuperacion e identidad de eventos.
No requieren RabbitMQ ni modifican bases locales.

La configuracion `tests/compose.integration.yml` requiere Docker Compose 2.24.4+
y usa puertos automaticos y volumenes aislados con el proyecto siguiente:

```bash
docker compose -p reactions-verification -f docker-compose.yml -f tests/compose.integration.yml up --build -d --wait
docker compose -p reactions-verification -f docker-compose.yml -f tests/compose.integration.yml exec -T reaction-service python - initial < tests/docker_probe.py
```

El probe tambien acepta `outage` tras detener el RabbitMQ de pruebas,
`pending` tras reiniciar la API y `recovered ID1,ID2` tras iniciar de nuevo el
broker. Los IDs se obtienen en la salida de `outage` y deben conservarse tras
reiniciar. El proyecto de pruebas no comparte volumenes con el despliegue normal.

## Persistencia y alcance

SQLite y una sola instancia de la API son la configuracion de este proyecto.
Para alta concurrencia, considera PostgreSQL y migraciones. `create_all` crea
tablas nuevas, incluida la outbox, pero no cambia tablas existentes: una base
antigua necesita migracion para incorporar restricciones que le falten.
Conserva el volumen SQLite, ya que contiene reacciones y eventos pendientes.
