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
    ollama_host: str = Field(default="http://localhost:11434", description="URL del servidor Ollama.")
    ollama_text_model: str = Field(
        default="deepseek-v4.1-flash:cloud", description="Modelo para mensajes de texto."
    )
    ollama_vision_model: str = Field(
        default="deepseek-v4.1-flash:cloud",
        description="Modelo de visión para imágenes y PDFs escaneados.",
    )
    ollama_think: bool = Field(
        default=False,
        description="Activa el razonamiento del modelo; apagado es más rápido y barato.",
    )
    ollama_timeout: float = Field(default=120.0, gt=0, description="Timeout (s) por llamada.")
    extraction_max_retries: int = Field(
        default=2, ge=0, le=5, description="Reintentos ante una respuesta inválida del modelo."
    )
    max_upload_bytes: int = Field(
        default=15 * 1024 * 1024, gt=0, description="Tamaño máximo de un archivo subido."
    )
    max_document_pages: int = Field(
        default=3, ge=1, le=10, description="Páginas máximas que se procesan de un PDF."
    )
    max_image_side: int = Field(
        default=1280, ge=256, description="Lado mayor (px) al que se reduce cada imagen."
    )
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
