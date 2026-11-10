# Control de calidad del servicio de búsqueda

Grupo «Búsqueda avanzada». Pruebas automáticas del microservicio de búsqueda
(`Tarea_Unidad_5_Despliegue/search/`). El código vive junto al servicio; esta carpeta
explica qué se probó y cómo correrlo.

## Cómo correrlas

```bash
cd Tarea_Unidad_5_Despliegue/search
pip install -r requirements-dev.txt
pytest                    # servicio + contrato: sin Docker ni Elasticsearch (27 pruebas)
pytest -m integration     # integración con Docker Compose (necesita Docker; ~5 min la primera vez)
```

## Qué cubre cada archivo (`search/tests/`)

| Archivo | Tipo | Qué prueba |
|---|---|---|
| `test_api.py` | servicio | Los 6 endpoints, cada uno con caso feliz y de error (422, 202, 503) |
| `test_contract_core.py` | contrato (consumidor) | El indexador procesa las respuestas pactadas del chat base y descarta las que rompen el contrato |
| `integration/test_compose.py` | integración + contrato (proveedor) | Chat base, indexador y Elasticsearch reales: el chat cumple el pacto y un mensaje nuevo aparece en la búsqueda |
| `contracts/chat_core.json` | pacto | Lo que el indexador espera de `channels` y `messages` (campos y tipos) |

## Decisiones

* **Aislamiento de la base de datos.** El servicio recibe Elasticsearch por
  `Depends(get_es)` (antes era una variable global). Las pruebas lo reemplazan con
  `FakeES` mediante `dependency_overrides`: no hay red ni datos reales. `queue_depth`
  (RabbitMQ) se reemplaza con `monkeypatch`. La integración usa un stack aparte
  (`integration/docker-compose.yaml`, puertos 18001-18004, sin volúmenes, se destruye
  al terminar), distinto del compose de desarrollo.
* **Qué verifica el falso.** No devuelve resultados «por magia»: las pruebas comprueban
  la consulta que el servicio le envía (filtros, enrutamiento por canal, orden, paginación)
  y cómo transforma la respuesta (highlights, campos internos ocultos). Que Elasticsearch
  interprete bien esa consulta lo cubre la prueba de integración.
* **Contrato.** El indexador es el consumidor del chat base. El pacto
  (`chat_core.json`) se verifica en ambos lados: contra un chat simulado en las pruebas
  de servicio y contra el chat real en la integración.
* **CI** (`.github/workflows/deploy-busqueda.yaml`): los jobs `test` e `integration`
  corren en cada push a `main` que toque `Tarea_Unidad_5_Despliegue/` o el workflow;
  `deploy` solo corre si ambos pasan (`needs`).
* **Cambio al servicio.** Solo `app/main.py`: `es = client()` pasó a `get_es()` con
  `Depends`. El comportamiento no cambia.

## Declaración de uso de IA

Se usó Claude Code (Claude Sonnet 5.5, de Anthropic) como asistente: ayudó a escribir las
pruebas, el pacto, el compose de integración, el cambio de `get_es` y el job de CI. El
grupo definió los requisitos, revisó y ejecutó el código y verificó el resultado. Los
commits hechos con la herramienta llevan `Co-Authored-By`.
