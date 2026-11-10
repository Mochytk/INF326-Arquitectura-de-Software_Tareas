"""Contrato que el indexador espera del chat base (formato inspirado en Pact).

`contracts/chat_core.json` lo escribe el consumidor (el indexador). Lo usan dos pruebas:
* `test_contract_core.py` (consumidor): el indexador funciona con esas respuestas.
* `integration/` (proveedor): el chat base real responde con esa forma.
"""
import json
from pathlib import Path

PYTHON_TYPES = {"string": str, "integer": int, "null": type(None)}


def load_pact() -> dict:
    return json.loads((Path(__file__).parent / "contracts" / "chat_core.json").read_text())


def interaction(description: str) -> dict:
    return next(i for i in load_pact()["interactions"] if i["description"] == description)


def violations(item: dict, item_types: dict[str, str]) -> list[str]:
    """Campos que faltan o que tienen un tipo distinto al pactado."""
    problems = []
    for field, spec in item_types.items():
        if field not in item:
            problems.append(f"falta `{field}`")
        elif not isinstance(item[field], tuple(PYTHON_TYPES[t] for t in spec.split("|"))):
            problems.append(f"`{field}` debería ser {spec}, es {type(item[field]).__name__}")
    return problems
