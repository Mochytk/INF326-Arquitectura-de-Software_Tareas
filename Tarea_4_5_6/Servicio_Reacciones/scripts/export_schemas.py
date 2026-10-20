"""Generate the HTTP, event and database contracts from the current code."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.database import Base
from app.main import app
from app.schemas.event import ReactionEvent


def main():
    destination = ROOT / "docs"
    destination.mkdir(exist_ok=True)
    for name, schema in {
        "openapi.json": app.openapi(),
        "reaction-event.schema.json": ReactionEvent.model_json_schema(),
    }.items():
        destination.joinpath(name).write_text(
            json.dumps(schema, indent=2, ensure_ascii=True) + "\n", encoding="ascii",
        )
    statements = []
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=sqlite.dialect())).strip() + ";")
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index).compile(dialect=sqlite.dialect())).strip() + ";")
    ddl = "\n\n".join(statements)
    destination.joinpath("schema.sql").write_text(
        "\n".join(line.rstrip() for line in ddl.splitlines()) + "\n", encoding="ascii",
    )
    print("Updated docs/openapi.json, docs/reaction-event.schema.json and docs/schema.sql")


if __name__ == "__main__":
    main()
