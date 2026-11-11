"""Modelos de entrada de datos extraídos (por el usuario, OCR o LLM)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FieldCandidate(BaseModel):
    """Valor candidato para un campo del contrato, aún sin validar."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str = Field(
        ...,
        min_length=1,
        description="Ruta con punto del campo destino.",
        examples=["employee.dni"],
    )
    value: Any = Field(..., description="Valor extraído, tal como llegó.", examples=["30123456"])
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confianza de la extracción (1.0 para datos escritos o confirmados por el usuario).",
        examples=[0.93],
    )
    source: str = Field(
        default="user",
        min_length=1,
        description="Origen del dato (p. ej. 'user', 'ocr:dni', 'llm').",
        examples=["ocr:dni"],
    )
