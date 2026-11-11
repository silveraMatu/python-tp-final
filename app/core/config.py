"""Configuración de la aplicación (variables de entorno con prefijo ``HUMANIA_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parámetros de ejecución; todos tienen un valor por defecto seguro."""

    model_config = SettingsConfigDict(env_prefix="HUMANIA_", env_file=".env", extra="ignore")

    database_path: Path = Field(
        default=Path("data/contracts.db"), description="Archivo SQLite del repositorio."
    )
    output_dir: Path = Field(
        default=Path("data/output"), description="Directorio de documentos generados."
    )
    template_path: Path = Field(
        default=Path("app/templates/contrato_trabajo_indeterminado.docx"),
        description="Plantilla .docx aprobada.",
    )
    city: str = Field(default="Córdoba", description="Ciudad de celebración del contrato.")
    confidence_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Confianza mínima para aceptar un dato extraído sin confirmación.",
    )


@lru_cache
def get_settings() -> Settings:
    """Instancia única de :class:`Settings`."""
    return Settings()
