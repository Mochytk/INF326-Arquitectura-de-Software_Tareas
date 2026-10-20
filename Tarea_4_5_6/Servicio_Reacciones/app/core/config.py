"""
Configuración Global.

Este archivo utiliza 'pydantic-settings' para cargar variables de entorno y
centralizar todas las configuraciones del microservicio (URLs, claves, etc.).
Por defecto toma los valores aquí definidos a menos que exista un archivo '.env'
o se inyecten mediante variables de entorno (como en Docker Compose).

Modifica este archivo si:
- Necesitas agregar una nueva variable de entorno al sistema.
- Quieres cambiar un puerto o ruta predeterminada.
"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Reaction Service"
    API_V1_STR: str = "/api/v1"

    # URL de la base de datos (por defecto creará un archivo SQLite llamado reactions.db)
    DATABASE_URL: str = "sqlite+aiosqlite:///./reactions.db"
    DATABASE_ECHO: bool = False

    # URLs de servicios externos a los cuales este servicio llama (consumidos)
    MESSAGES_SERVICE_URL: str = "http://messages-service:8000/api/v1/messages"
    USERS_SERVICE_URL: str = "http://users-service:8000/api/v1/users"
    EXTERNAL_VALIDATION_ENABLED: bool = False
    VALIDATION_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0)
    VALIDATION_SIMULATED_NOT_FOUND_ID: str = "not-found"

    # Configuración de RabbitMQ
    EVENTS_ENABLED: bool = True
    EVENTS_REQUIRED: bool = False
    EVENT_BROKER_URL: str = "amqp://reactions:reactions_dev@localhost:5672/"
    EVENT_EXCHANGE: str = "reactions"
    EVENT_QUEUE: str = "reactions.events"
    EVENT_ROUTING_KEY_PREFIX: str = "reaction"
    EVENT_PUBLISH_RETRIES: int = Field(default=3, ge=1)
    EVENT_PUBLISH_RETRY_DELAY_SECONDS: float = Field(default=0.5, ge=0)
    EVENT_TIMEOUT_SECONDS: float = Field(default=3.0, gt=0)
    OUTBOX_POLL_INTERVAL_SECONDS: float = Field(default=1.0, gt=0)
    OUTBOX_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    HEALTHCHECK_TIMEOUT_SECONDS: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def validate_event_settings(self):
        if self.EVENTS_REQUIRED and not self.EVENTS_ENABLED:
            raise ValueError("EVENTS_REQUIRED requires EVENTS_ENABLED=true")
        return self

    class Config:
        # Permite leer estas variables desde un archivo local llamado '.env' si existe
        env_file = ".env"
        extra = "ignore"

# Instancia global que será importada en todo el resto de la app
settings = Settings()
