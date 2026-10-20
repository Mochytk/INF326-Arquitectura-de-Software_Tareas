"""
Esquemas Pydantic para la validación y documentación de datos.

Aquí se definen las estructuras de los datos de entrada (lo que nos envía el cliente
en el body del request) y salida (lo que le respondemos al cliente).
Pydantic se encarga automáticamente de validar tipos, obligatoriedad de campos
y generar la documentación de Swagger.

Modifica este archivo si necesitas:
- Agregar un nuevo campo a lo que se pide en el POST (ej: fecha, plataforma).
- Cambiar cómo se muestra la información al devolver un GET.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

class ReactionBase(BaseModel):
    """
    Clase base con campos comunes a varias estructuras.
    """
    message_id: str = Field(..., min_length=1, max_length=128, description="ID del mensaje al cual se reacciona", examples=["msg-1234"])
    user_id: str = Field(..., min_length=1, max_length=128, description="ID del usuario que realiza la reacción", examples=["usr-5678"])
    reaction_type: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$", description="Nombre de reaccion; se normaliza a minusculas (ej: like, heart, sad)", examples=["like"])

    @field_validator("message_id", "user_id", "reaction_type", mode="before")
    @classmethod
    def normalize_text(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized.lower() if info.field_name == "reaction_type" else normalized

class ReactionCreate(ReactionBase):
    """
    Esquema utilizado para recibir los datos de creación (Body del POST).
    Hereda todo de ReactionBase.
    """
    pass

class ReactionResponse(ReactionBase):
    """
    Esquema utilizado para la respuesta cuando se crea o se solicita una reacción individual.
    Añade los campos generados por el sistema (id, created_at).
    """
    id: str = Field(..., description="Identificador único de la reacción", example="reac-9012")
    created_at: datetime = Field(..., description="Fecha y hora de la creación")

    # Esto permite a Pydantic leer los objetos ORM de SQLAlchemy y transformarlos a JSON
    model_config = ConfigDict(from_attributes=True)

class ReactionSummary(BaseModel):
    """
    Esquema para un resumen de contadores por tipo de reacción.
    Ej: reaction_type='like', count=5
    """
    reaction_type: str
    count: int

class MessageReactionsResponse(BaseModel):
    """
    Esquema utilizado para responder a un GET del listado de reacciones de un mensaje.
    Retorna el id del mensaje, conteo total, el resumen por tipo, y la lista detallada.
    """
    message_id: str
    total_reactions: int
    summary: list[ReactionSummary]
    reactions: list[ReactionResponse]
