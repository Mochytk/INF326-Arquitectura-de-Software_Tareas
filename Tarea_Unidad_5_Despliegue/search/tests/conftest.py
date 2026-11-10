"""Fixtures compartidas: un Elasticsearch falso en lugar del real.

El servicio recibe el cliente de Elasticsearch por `Depends(get_es)`, así que cada
prueba lo reemplaza con `FakeES` mediante `dependency_overrides`. Ninguna prueba de
este directorio abre una conexión de red ni toca datos reales.
"""
import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import NotFoundError
from fastapi.testclient import TestClient

from app import main


def not_found_error() -> NotFoundError:
    meta = ApiResponseMeta(status=404, http_version="1.1", headers=HttpHeaders(),
                           duration=0.0, node=NodeConfig("http", "localhost", 9200))
    return NotFoundError("index_not_found_exception", meta=meta, body={})


class FakeES:
    """Responde lo que se le configure y recuerda cómo se le consultó."""

    def __init__(self):
        self.hits: list[dict] = []
        self.total = 0
        self.alive = True
        self.count_value = 0
        self.error: Exception | None = None   # se lanza en search() y count()
        self.last_search: dict = {}

    def search(self, **kwargs):
        if self.error:
            raise self.error
        self.last_search = kwargs
        return {"hits": {"total": {"value": self.total}, "hits": self.hits}}

    def count(self, **kwargs):
        if self.error:
            raise self.error
        return {"count": self.count_value}

    def ping(self):
        return self.alive


@pytest.fixture
def fake_es():
    return FakeES()


@pytest.fixture
def client(fake_es):
    main.app.dependency_overrides[main.get_es] = lambda: fake_es
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
