"""Integración con Docker Compose: chat base real + indexador + Elasticsearch real.

Levanta un stack desechable (`docker-compose.yaml` de esta carpeta), crea datos por las
APIs públicas y comprueba el flujo completo. Se ejecuta con:  pytest -m integration
"""
import subprocess
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.contract import interaction, violations

pytestmark = pytest.mark.integration

COMPOSE = ["docker", "compose", "-f", str(Path(__file__).parent / "docker-compose.yaml")]
USERS, CHANNELS, MESSAGES, SEARCH = (f"http://localhost:1800{n}" for n in (1, 2, 3, 4))


def wait_until(check, timeout=120, pause=2):
    """Repite `check()` hasta que devuelva algo verdadero; falla si se agota el tiempo."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = check()
            if result:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(pause)
    pytest.fail("se agotó el tiempo esperando al stack")


@pytest.fixture(scope="module")
def stack():
    subprocess.run([*COMPOSE, "up", "-d", "--build"], check=True)
    try:
        for url in (USERS, CHANNELS, MESSAGES, SEARCH):
            wait_until(lambda url=url: httpx.get(f"{url}/health").status_code == 200)
        wait_until(lambda: httpx.get(f"{SEARCH}/health/ready").status_code == 200)
        yield
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], check=False)  # -v: borra los datos


@pytest.fixture(scope="module")
def chat(stack):
    """Un usuario, un canal y un mensaje creados por las APIs del chat base."""
    word = f"integracion{uuid.uuid4().hex[:8]}"  # palabra única: no choca con otros datos
    user = httpx.post(f"{USERS}/api/v1/users", json={"display_name": "Ana"}).json()
    channel = httpx.post(f"{CHANNELS}/api/v1/channels", json={"name": "general"}).json()
    message = httpx.post(f"{MESSAGES}/api/v1/channels/{channel['id']}/messages",
                         json={"author_id": user["id"], "content": f"hola {word}"}).json()
    return {"word": word, "channel": channel, "message": message}


def test_el_chat_base_real_cumple_el_contrato(chat):
    canales = httpx.get(f"{CHANNELS}/api/v1/channels").json()
    mensajes = httpx.get(f"{MESSAGES}/api/v1/channels/{chat['channel']['id']}/messages").json()

    for pacto, items in (("listar canales", canales), ("listar mensajes de un canal", mensajes)):
        assert items, pacto
        for item in items:
            assert violations(item, interaction(pacto)["response"]["item_types"]) == [], pacto


def test_un_mensaje_nuevo_aparece_en_la_busqueda(chat):
    def encontrado():
        body = httpx.get(f"{SEARCH}/api/v1/search/messages",
                         params={"content": chat["word"]}).json()
        return body if body.get("total_results") else None

    body = wait_until(encontrado)
    assert body["messages"][0]["id"] == chat["message"]["id"]
    assert f"**{chat['word']}**" in body["messages"][0]["highlights"][0]


def test_la_busqueda_real_rechaza_parametros_invalidos(stack):
    assert httpx.get(f"{SEARCH}/api/v1/search/messages", params={"limit": 0}).status_code == 422
