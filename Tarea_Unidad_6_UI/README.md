# API Gateway GraphQL e interfaz del chat

Grupo «Búsqueda avanzada». Un gateway GraphQL (Node, `graphql-yoga` + `dataloader`) une
cinco servicios REST y sirve una interfaz web mínima que usa solo ese gateway:

```
 navegador ──► gateway :4000 ──► users · channels · messages   (núcleo del curso)
  (UI + GraphQL)     │       ──► search     (Búsqueda, Elasticsearch)   Tarea 4
                     │       ──► media      (adjuntos y previews de links)
                     └───────► reactions    (reacciones a mensajes)
```

* **UI** (`gateway/public/`): canales, mensajes, reacciones, adjuntos (subir, descargar,
  borrar), previews de links, búsqueda y estado de los servicios. Abajo muestra la
  última consulta GraphQL enviada. GraphiQL está en `/graphql`.
* **Gateway** (`gateway/src/`): `schema.js` (esquema y resolvers), `loaders.js`
  (DataLoaders), `upstream.js` (llamadas HTTP con timeout y errores tipados),
  `server.js` (HTTP, UI estática y proxy de descargas).

## Una consulta, varios servicios

```graphql
{
  channel(id: "…") {
    name
    messages(limit: 20) {            # messages
      content
      author { displayName }         # users
      reactions { total counts { type count } }   # reactions
      previews { title imageUrl }    # media
    }
    attachments { filename uploader { displayName } }   # media
    quota { usedBytes limitBytes }
  }
  search(content: "entrega") { total messages { highlights author { displayName } } }  # search
}
```

Los argumentos viajan en la misma consulta (`messages(limit:)`, `attachments(category:)`,
`search(authorIds:, has:, …)`), así que el cliente no necesita dos viajes.

## DataLoader y el problema N+1

Sin loaders, 20 mensajes serían 20 llamadas a `users`, 20 a `reactions` y 20 a `media`.
`loaders.js` crea, por request, un loader de `user`, `channel`, `reactions` y `preview`:
agrupa las llaves pedidas en un mismo tick, **elimina las repetidas** y cachea el
resultado durante la consulta. La prueba `test/gateway.test.js` lo mide contra un
upstream simulado: 12 mensajes de 3 autores con la misma URL hacen **3** llamadas a
`users`, **1** a `media` y 12 a `reactions`.

Limitación honesta: ningún servicio tiene un endpoint por lote (`GET /messages/{id}/reactions`
es uno por mensaje), así que el lote se despacha en paralelo (máx. 8 a la vez) en vez de
una sola llamada. Un `POST /reactions/batch` en Reacciones lo reduciría a una.

## Errores parciales

Los campos que vienen de Media y Reacciones son nulables. Si uno de esos servicios cae,
el resto de la consulta responde y el error queda en `errors[]` con
`extensions: { code, service }` (la UI lo muestra en una franja). Media exige el header
`X-User-Id`; el gateway lo reenvía tal como llega y responde `UNAUTHENTICATED` si falta.
Igual que en Media, **no autentica**: es solo identificación.

## Correr en local

```bash
docker compose up --build        # desde esta carpeta; abrir http://localhost:4000
cd gateway && npm ci && npm test # pruebas del gateway (sin Docker)
```

El compose incluye el de `Servicio_Media` (núcleo + Media + red `microsvcs`) y agrega
Elasticsearch, Búsqueda, su indexador, Reacciones y el gateway.
Reacciones corre con `EVENTS_ENABLED=false` (sin broker) y
`EXTERNAL_VALIDATION_ENABLED=false`, porque su validador pide `GET /messages/{id}` y el
núcleo no lo expone.

## Kubernetes

* `k8s/gateway.yaml`: ConfigMap con las URLs, Deployment (probes, no-root) y Service.
* CI: `.github/workflows/deploy-gateway.yaml` corre las pruebas y, si pasan, construye la
  imagen `ghcr.io/mochytk/busqueda-gateway` y aplica `k8s/`.
* Pendiente: `k8s/pendiente/ingress.yaml` (host a confirmar con el ayudante) y las URLs de
  `MEDIA_URL`/`REACTIONS_URL` del ConfigMap, que apuntan a nombres que aún no existen
  mientras esos equipos no desplieguen. Hasta entonces esos campos responden `null` + error.

## Limitaciones conocidas

* `Channel.messages` trae todo el canal desde el núcleo (no pagina) y corta en el gateway.
* La subida de archivos pasa entera por memoria del gateway.
* `Attachment.url`/mensajes de tipo link de la galería no se han probado contra datos reales.
* Video de demostración: pendiente.
