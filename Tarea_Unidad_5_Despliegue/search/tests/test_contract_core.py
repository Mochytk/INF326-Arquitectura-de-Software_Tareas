"""Prueba de contrato (lado consumidor): el indexador contra un chat base simulado.

Un servidor HTTP local responde con los ejemplos del pacto. Si el indexador deja de
entender esa forma (o alguien edita el pacto con un ejemplo inválido), la prueba falla.
El lado proveedor (el chat base real cumple el pacto) está en `integration/`.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import indexer
from tests.contract import interaction, violations

CHANNELS = interaction("listar canales")
MESSAGES = interaction("listar mensajes de un canal")


class FakeCore(BaseHTTPRequestHandler):
    """Sirve las respuestas de ejemplo del pacto."""
    messages = MESSAGES["response"]["example"]

    def do_GET(self):
        if self.path == CHANNELS["request"]["path"]:
            body = CHANNELS["response"]["example"]
        elif self.path == "/api/v1/channels/c1/messages":
            body = self.messages
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):  # silencia el log de cada request
        pass


class FakeBulkES:
    """Guarda las operaciones `_bulk` y responde éxito para cada documento."""

    def __init__(self):
        self.operations = []

    def bulk(self, operations):
        self.operations = operations
        return {"items": [{"create": {"_id": op["create"]["_id"], "status": 201}}
                          for op in operations[::2]]}


@pytest.fixture
def core(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeCore)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(indexer, "CHANNELS_URL", url)
    monkeypatch.setattr(indexer, "MESSAGES_URL", url)
    yield url
    server.shutdown()


@pytest.fixture
def es(monkeypatch):
    fake = FakeBulkES()
    monkeypatch.setattr(indexer, "es", fake)
    return fake


@pytest.mark.parametrize("pacto", [CHANNELS, MESSAGES], ids=["canales", "mensajes"])
def test_los_ejemplos_del_pacto_cumplen_sus_propios_tipos(pacto):
    for item in pacto["response"]["example"]:
        assert violations(item, pacto["response"]["item_types"]) == []


def test_el_indexador_indexa_las_respuestas_del_pacto(core, es):
    messages = list(indexer.fetch_messages())
    done = indexer.index(messages)

    assert done == {"m1"}
    document = es.operations[1]
    assert document["id"] == "m1" and document["channel_id"] == "c1"
    assert document["has"] == ["link", "mention"]           # derivado del contenido
    assert document["mentions"] == ["11111111-1111-1111-1111-111111111111"]
    assert es.operations[0]["create"]["routing"] == "c1"    # enrutado por canal


def test_un_mensaje_que_rompe_el_contrato_se_descarta_sin_caerse(core, es, monkeypatch):
    sin_autor = {k: v for k, v in MESSAGES["response"]["example"][0].items()
                 if k != "author_id"}
    monkeypatch.setattr(FakeCore, "messages", [sin_autor])

    done = indexer.index(list(indexer.fetch_messages()))

    assert done == {"m1"}        # se marca como visto para no reintentarlo siempre
    assert es.operations == []   # y no se envía nada a Elasticsearch
