"""
Modelos ORM de SQLAlchemy.

Este archivo mapea las clases de Python hacia tablas en la base de datos relacional.
Cada atributo de la clase representa una columna de la tabla.

Modifica este archivo si necesitas:
- Agregar una nueva columna a la base de datos (ej: 'updated_at').
- Cambiar el tipo de dato de una columna o agregar índices/llaves foráneas.
"""

from sqlalchemy import Column, String, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import DateTime
from app.core.database import Base
import uuid

def generate_uuid():
    """Genera un identificador único en formato de cadena."""
    return str(uuid.uuid4())

class Reaction(Base):
    """
    Modelo representativo de la tabla 'reactions' en la BD.
    """
    __tablename__ = "reactions"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            "reaction_type",
            name="uq_reaction_message_user_type",
        ),
    )

    # ID primario. Lo autogeneramos usando la función generate_uuid() por defecto.
    id = Column(String, primary_key=True, index=True, default=generate_uuid)

    # Índices (index=True) agregados para agilizar las búsquedas
    # frecuentemente usadas (ej. obtener reacciones por mensaje o por usuario).
    message_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)

    reaction_type = Column(String, nullable=False)

    # Fecha de creación. 'server_default=func.now()' delegará a la base de datos
    # la tarea de rellenarlo con la hora actual al insertar.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
