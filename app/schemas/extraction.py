"""Modelos de entrada de datos extraídos (por el usuario, OCR o LLM)."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


FieldPath = Literal[
    "employee.nombre",
    "employee.apellido",
    "employee.dni",
    "employee.cuil",
    "employee.domicilio",
    "employee.fecha_nacimiento",
    "company.razon_social",
    "company.cuit",
    "company.domicilio_legal",
    "company.apoderado_nombre",
    "company.apoderado_cargo",
    "terms.puesto_funcion",
    "terms.fecha_inicio",
    "terms.modalidad",
    "terms.remuneracion_bruta",
    "terms.jornada_laboral",
    "terms.lugar_trabajo",
]


class ExtractedField(BaseModel):
    """Un dato tal como lo devuelve el LLM (salida restringida por JSON Schema).

    ``field_name`` solo admite rutas del esquema del contrato: el modelo no puede
    proponer campos nuevos.
    """

    model_config = ConfigDict(extra="forbid")

    field_name: FieldPath = Field(..., description="Ruta del campo del contrato.")
    value: Optional[str] = Field(
        default=None, max_length=300, description="Valor encontrado, o null si el dato no aparece."
    )
    evidence: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Fragmento literal del texto o documento del que se leyó el valor.",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confianza de 0.0 a 1.0 en el valor."
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def _trim_evidence(cls, value: Any) -> Any:
        """La evidencia solo sirve para contrastar con la fuente: un exceso se recorta, no falla."""
        return value[:500] if isinstance(value, str) else value

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> Any:
        if isinstance(value, bool):
            return value
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return value


class LLMExtractionPayload(BaseModel):
    """Respuesta completa del LLM: lista de datos encontrados."""

    model_config = ConfigDict(extra="forbid")

    fields: List[ExtractedField] = Field(default_factory=list, max_length=40)
