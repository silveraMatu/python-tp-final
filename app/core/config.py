"""Configuración de la aplicación (variables de entorno con prefijo ``HUMANIA_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiUserConfig(BaseModel):
    """Usuario de la API: nombre, rol y hash SHA-256 de su API key (nunca la key)."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[\w.\-@]+$")
    role: Literal["REQUESTER", "REVIEWER"]
    key_sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")


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
    soffice_path: str = Field(
        default="soffice", description="Ejecutable de LibreOffice para convertir DOCX a PDF."
    )
    pdf_timeout: float = Field(default=90.0, gt=0, description="Timeout (s) de cada conversión.")
    timezone: str = Field(
        default="America/Argentina/Cordoba",
        description="Zona horaria para las fechas que se imprimen en el documento.",
    )
    embedding_model: str = Field(
        default="nomic-embed-text", description="Modelo de embeddings (local, vía Ollama)."
    )
    chroma_path: Path = Field(
        default=Path("data/chroma"), description="Directorio de la base vectorial ChromaDB."
    )
    knowledge_dir: Path = Field(
        default=Path("data/knowledge"),
        description="Documentos (PDF/MD/TXT) que alimentan las consultas del RAG.",
    )
    rag_top_k: int = Field(default=6, ge=1, le=20, description="Fragmentos recuperados por consulta.")
    rag_min_score: float = Field(
        default=0.5,
        ge=-1.0,
        le=1.0,
        description="Similitud coseno mínima para considerar relevante un fragmento.",
    )
    api_users: List[ApiUserConfig] = Field(
        default_factory=list,
        description="Usuarios de la API (JSON). Sin usuarios, la API rechaza todo pedido.",
    )
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="Orígenes del frontend autorizados (CORS).",
    )
    max_upload_files: int = Field(
        default=5, ge=1, le=20, description="Archivos máximos por mensaje."
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
