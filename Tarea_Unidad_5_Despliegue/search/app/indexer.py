"""Indexador: copia los mensajes del chat base a Elasticsearch por polling.

El core desplegado en el cluster no publica eventos (no hay broker), así que
cada POLL_SECONDS se listan los canales (`channels`) y sus mensajes (`messages`)
usando solo sus APIs públicas. El indexado es idempotente: cada documento usa el
id del mensaje con `op_type=create`, y un 409 significa "ya indexado".

Sigue siendo consistencia eventual: un mensaje nuevo aparece en la búsqueda
tras el siguiente ciclo de polling (POLL_SECONDS) más el refresh de ES (1 s).
"""
import json
import logging
import os
import time
from pathlib import Path
from urllib.request import urlopen

from elasticsearch import ApiError, TransportError

from app.index import ALIAS, client, ensure_index, to_document, wait_for

CHANNELS_URL = os.environ.get("CHANNELS_URL", "http://channels:8000")
MESSAGES_URL = os.environ.get("MESSAGES_URL", "http://messages:8000")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "5"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "200"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s indexer %(message)s")
logging.getLogger("elastic_transport").setLevel(logging.WARNING)
log = logging.getLogger("indexer")
es = client()
# El indexador no tiene HTTP: la livenessProbe de Kubernetes (exec) revisa que
# este archivo se haya tocado hace poco (p. ej. `find /tmp/heartbeat -mmin -1`).
HEARTBEAT_FILE = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat"))


def beat() -> None:
    HEARTBEAT_FILE.touch()


def get_json(url: str):
    with urlopen(url, timeout=5) as response:
        return json.load(response)


def fetch_messages():
    """Todos los mensajes de todos los canales (el core no pagina)."""
    for channel in get_json(f"{CHANNELS_URL}/api/v1/channels"):
        yield from get_json(f"{MESSAGES_URL}/api/v1/channels/{channel['id']}/messages")


def index(messages: list[dict]) -> set[str]:
    """Envía un lote con `_bulk`; devuelve los ids que ya no hay que reintentar."""
    operations, done = [], set()
    for message in messages:
        try:
            document = to_document(message)
        except (KeyError, TypeError):
            log.error("invalid message skipped: %s", message.get("id"))
            done.add(message.get("id"))  # reintentarlo no lo arreglaría
            continue
        operations += [{"create": {"_index": ALIAS, "_id": document["id"],
                                   "routing": document["channel_id"]}}, document]
    if not operations:
        return done
    indexed = 0
    for item in es.bulk(operations=operations)["items"]:
        result = item["create"]
        if result["status"] < 300:
            indexed += 1
        if result["status"] < 300 or result["status"] == 409:  # 409: ya estaba
            done.add(result["_id"])
        else:
            log.error("rejected %s: %s", result["_id"], result.get("error"))
    log.info("bulk: %d indexed, %d already there", indexed, len(done) - indexed)
    return done


def run() -> None:
    wait_for(es)
    ensure_index(es)
    # shortcut: ids vistos solo en memoria (al reiniciar se reenvía todo una vez,
    # sin duplicar por el 409); pasar a un cursor persistido si el volumen crece.
    seen: set[str] = set()
    log.info("polling %s every %.0fs", MESSAGES_URL, POLL_SECONDS)
    while True:
        beat()
        try:
            new = [m for m in fetch_messages() if m.get("id") not in seen]
            for start in range(0, len(new), BATCH_SIZE):
                seen |= index(new[start:start + BATCH_SIZE])
        except (OSError, ValueError, ApiError, TransportError) as error:
            # Core o Elasticsearch caídos: se reintenta en el siguiente ciclo.
            log.warning("poll failed: %r", error)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
