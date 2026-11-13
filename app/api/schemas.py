"""Modelos de entrada y salida de la API REST."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.contract import ContractStatus


class FieldValueOut(BaseModel):
    """Dato cargado, listo para mostrar."""

    field_name: str = Field(..., examples=["employee.dni"])
    label: str = Field(..., examples=["DNI del empleado/a"])
    value: str = Field(..., examples=["30.123.456"])


class PendingConflictOut(BaseModel):
    """Dato que espera la confirmación del usuario."""

    field_name: str
    label: str
    value: str = Field(..., description="Valor leído, pendiente de confirmar.")
    detail: Optional[str] = Field(default=None, description="Motivo de la confirmación.")


class ContractOut(BaseModel):
    """Estado de un contrato."""

    id: UUID
    status: ContractStatus
    status_label: str
    created_by: Optional[str]
    is_complete: bool
    missing_fields: List[str]
    fields: List[FieldValueOut]
    pending_conflicts: List[PendingConflictOut]
    issues: List[str] = Field(
        default_factory=list, description="Inconsistencias entre campos que bloquean el envío."
    )
    allowed_actions: List[str] = Field(
        default_factory=list, description="Acciones disponibles para el usuario actual."
    )


class DocumentLinkOut(BaseModel):
    """Enlace de descarga (relativo a la API)."""

    kind: Literal["draft", "final"]
    format: Literal["pdf", "docx"]
    url: str


class MessageOut(BaseModel):
    """Respuesta del agente a un mensaje."""

    reply: str
    intent: str
    classification_source: str
    contract: ContractOut
    documents: List[DocumentLinkOut] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)


class ConflictResolutionIn(BaseModel):
    """Decisión explícita sobre un dato pendiente."""

    model_config = ConfigDict(extra="forbid")

    field_name: str = Field(..., min_length=1, examples=["employee.dni"])
    accept_new: bool = Field(..., description="True usa el valor leído; False lo descarta.")


class ReviewIn(BaseModel):
    """Decisión del revisor humano."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    comment: Optional[str] = Field(default=None, max_length=500)


class AuditEntryOut(BaseModel):
    """Entrada de la auditoría de un contrato."""

    timestamp: datetime
    actor: str
    action: str
    status: ContractStatus
    detail: Optional[str] = None


class VerificationOut(BaseModel):
    """Resultado de verificar el documento final emitido."""

    ok: bool
    problems: List[str]
    verification_code: Optional[str]


class TemplateOut(BaseModel):
    """Plantilla disponible (o no) para una modalidad."""

    modality: str
    label: str
    available: bool
    required_fields: List[str]


class KnowledgeQueryIn(BaseModel):
    """Consulta a la documentación institucional."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=3, max_length=1000)


class KnowledgeAnswerOut(BaseModel):
    """Respuesta de la documentación, con sus fuentes."""

    answer: str
    found: bool
    sources: List[str]


class MeOut(BaseModel):
    """Usuario autenticado."""

    name: str
    role: Literal["REQUESTER", "REVIEWER"]


class ErrorOut(BaseModel):
    """Formato de error de la API."""

    error: str = Field(..., examples=["invalid_state_transition"])
    detail: str
