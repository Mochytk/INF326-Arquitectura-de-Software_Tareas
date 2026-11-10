"""Pruebas de servicio: cada endpoint con un caso feliz y al menos un error."""
import pytest
from elasticsearch import TransportError

from app import main
from tests.conftest import not_found_error

HIT = {"_source": {"id": "m1", "channel_id": "c1", "author_id": "u1",
                   "content": "la reunión es el jueves", "mentions": [],
                   "links": [], "has": [], "created_at": "2026-01-01T10:00:00Z",
                   "deleted": False, "indexed_at": "2026-01-01T10:00:02Z"},
       "highlight": {"content": ["la **reunión** es el jueves"]}}


# --- GET /health ---------------------------------------------------------------

def test_health_responde_ok(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_health_no_depende_de_elasticsearch(client, fake_es):
    fake_es.alive = False  # liveness no debe mirar dependencias
    assert client.get("/health").status_code == 200


# --- GET /health/ready ---------------------------------------------------------

def test_ready_ok_si_elasticsearch_responde(client):
    assert client.get("/health/ready").status_code == 200


def test_ready_503_si_elasticsearch_no_responde(client, fake_es):
    fake_es.alive = False
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Elasticsearch unavailable"}


# --- GET /api/v1/search/messages -----------------------------------------------

def test_busqueda_global_devuelve_mensajes_con_highlights(client, fake_es):
    fake_es.hits, fake_es.total = [HIT], 1
    body = client.get("/api/v1/search/messages", params={"content": "reunión"}).json()
    assert body["total_results"] == 1
    message = body["messages"][0]
    assert message["id"] == "m1" and message["hit"] is True
    assert message["highlights"] == ["la **reunión** es el jueves"]
    assert "indexed_at" not in message and "deleted" not in message  # campos internos


def test_busqueda_global_construye_filtros(client, fake_es):
    client.get("/api/v1/search/messages", params={
        "content": "hola", "author_id": ["u1"], "channel_id": ["c1", "c2"],
        "mentions": ["u2"], "has": ["link"], "limit": 5, "offset": 10})
    call = fake_es.last_search
    filters = call["query"]["bool"]["filter"]
    assert {"term": {"deleted": False}} in filters      # nunca devuelve borrados
    assert {"terms": {"author_id": ["u1"]}} in filters
    assert {"terms": {"channel_id": ["c1", "c2"]}} in filters
    assert {"term": {"mentions": "u2"}} in filters
    assert {"term": {"has": "link"}} in filters
    assert call["query"]["bool"]["must"][0]["match"]["content"]["query"] == "hola"
    assert (call["size"], call["from_"], call["routing"]) == (5, 10, "c1,c2")


def test_busqueda_sin_texto_no_tiene_condicion_must(client, fake_es):
    client.get("/api/v1/search/messages")
    assert fake_es.last_search["query"]["bool"]["must"] == []


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": main.MAX_LIMIT + 1}, {"offset": -1},
    {"offset": main.MAX_OFFSET + 1}, {"sort_by": "nombre"}, {"has": "video"},
    {"min_date": "ayer"}, {"content": "x" * 1025}])
def test_busqueda_global_rechaza_parametros_invalidos(client, params):
    assert client.get("/api/v1/search/messages", params=params).status_code == 422


def test_busqueda_responde_202_si_el_indice_no_existe(client, fake_es):
    fake_es.error = not_found_error()
    response = client.get("/api/v1/search/messages", params={"content": "hola"})
    assert response.status_code == 202
    assert response.headers["retry-after"] == "2"


def test_busqueda_responde_503_si_elasticsearch_falla(client, fake_es):
    fake_es.error = TransportError("conexión rechazada")
    response = client.get("/api/v1/search/messages", params={"content": "hola"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Search unavailable"}


# --- GET /api/v1/channels/{channel_id}/messages/search -------------------------

def test_busqueda_en_canal_limita_al_canal(client, fake_es):
    fake_es.hits, fake_es.total = [HIT], 1
    body = client.get("/api/v1/channels/c1/messages/search",
                      params={"content": "reunión"}).json()
    assert body["total_results"] == 1
    assert {"terms": {"channel_id": ["c1"]}} in fake_es.last_search["query"]["bool"]["filter"]
    assert fake_es.last_search["routing"] == "c1"


def test_busqueda_en_canal_ordena_por_relevancia_solo_con_texto(client, fake_es):
    client.get("/api/v1/channels/c1/messages/search",
               params={"content": "hola", "sort_by": "relevance"})
    assert fake_es.last_search["sort"][0] == "_score"
    client.get("/api/v1/channels/c1/messages/search", params={"sort_by": "relevance"})
    assert fake_es.last_search["sort"][0] != "_score"  # sin texto no hay relevancia


def test_busqueda_en_canal_rechaza_orden_invalido(client):
    response = client.get("/api/v1/channels/c1/messages/search",
                          params={"sort_order": "arriba"})
    assert response.status_code == 422


def test_busqueda_en_canal_503_si_elasticsearch_falla(client, fake_es):
    fake_es.error = TransportError("caído")
    assert client.get("/api/v1/channels/c1/messages/search").status_code == 503


# --- GET /api/v1/search/status -------------------------------------------------

def test_status_informa_documentos_y_colas(client, fake_es, monkeypatch):
    fake_es.count_value = 42
    colas = {"search.indexer": 3, "search.indexer.dlq": 0}
    monkeypatch.setattr(main, "queue_depth", colas.get)  # evita llamar a RabbitMQ
    assert client.get("/api/v1/search/status").json() == {
        "indexed_documents": 42, "pending_events": 3, "dead_letter_events": 0}


def test_status_tolera_elasticsearch_y_rabbitmq_caidos(client, fake_es, monkeypatch):
    fake_es.error = TransportError("caído")
    monkeypatch.setattr(main, "queue_depth", lambda name: None)
    response = client.get("/api/v1/search/status")
    assert response.status_code == 200
    assert response.json() == {"indexed_documents": None, "pending_events": None,
                               "dead_letter_events": None}
