"""Modelos y puerto del historial de conversación de un contrato."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Protocol, Sequence
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRole(str, Enum):
    """Quién dice cada mensaje."""

    USER = "user"  # el solicitante
    AGENT = "agent"  # el asistente
    SYSTEM = "system"  # eventos: confirmaciones, envío a revisión, decisiones del revisor


class AttachmentMeta(BaseModel):
    """Archivo adjunto a un mensaje del usuario."""

    id: UUID
    filename: str = Field(..., examples=["dni.png"])
    media_type: str = Field(..., examples=["image/png"])
    size_bytes: int
    sha256: str
    url: str = Field(..., description="Ruta relativa para descargarlo (requiere X-API-Key).")


class DocumentRef(BaseModel):
    """Documento generado a partir de una respuesta (p. ej. el borrador)."""

    kind: Literal["draft", "final"]
    format: Literal["pdf", "docx"]
    url: str


class ChatMessage(BaseModel):
    """Mensaje del historial."""

    id: UUID
    seq: int = Field(..., description="Orden dentro del contrato (1, 2, 3, ...).")
    timestamp: datetime
    role: ChatRole
    actor: str = Field(..., description="Usuario que originó el mensaje; 'assistant' para el agente.")
    text: str
    intent: Optional[str] = Field(default=None, description="Solo en respuestas del agente.")
    classification_source: Optional[str] = None
    sources: List[str] = Field(default_factory=list, description="Fuentes citadas (consultas).")
    documents: List[DocumentRef] = Field(default_factory=list)
    attachments: List[AttachmentMeta] = Field(default_factory=list)


class ChatPage(BaseModel):
    """Página del historial, en orden cronológico (más antiguo primero)."""

    items: List[ChatMessage]
    has_more: bool = Field(..., description="Hay mensajes anteriores a los devueltos.")
    next_before: Optional[int] = Field(
        default=None, description="Valor para el parámetro 'before' de la página anterior."
    )


@dataclass(frozen=True)
class NewAttachment:
    """Adjunto ya guardado en disco, listo para registrar."""

    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    stored_name: str


@dataclass(frozen=True)
class NewMessage:
    """Mensaje por agregar al historial."""

    role: ChatRole
    actor: str
    text: str
    intent: Optional[str] = None
    classification_source: Optional[str] = None
    sources: Sequence[str] = ()
    documents: Sequence[DocumentRef] = ()
    attachments: Sequence[NewAttachment] = field(default_factory=tuple)


@dataclass(frozen=True)
class StoredAttachment:
    """Adjunto registrado, con el nombre de archivo en disco."""

    meta: AttachmentMeta
    stored_name: str


class ChatRepository(Protocol):
    """Persistencia del historial."""

    def append(self, contract_id: UUID, messages: Sequence[NewMessage]) -> List[ChatMessage]:
        """Agrega los mensajes, en orden y en una sola transacción."""
        ...

    def page(self, contract_id: UUID, limit: int, before: Optional[int] = None) -> ChatPage:
        """Hasta ``limit`` mensajes con ``seq < before`` (los más recientes primero en el corte)."""
        ...

    def get_attachment(self, contract_id: UUID, attachment_id: UUID) -> Optional[StoredAttachment]:
        """Adjunto del contrato, o ``None`` si no existe."""
        ...
