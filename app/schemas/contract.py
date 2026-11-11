"""Capa de dominio del Agente de Generación de Contratos Laborales (HumanIA S.A.).

Este módulo es la *Single Source of Truth* del contrato: todos los modelos son
estrictos (``extra="forbid"``) para que ni el OCR ni el LLM puedan inyectar
campos no previstos, y toda la validación es determinista (sin heurísticas).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Type
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class ContractStatus(str, Enum):
    """Estado del contrato dentro del flujo del agente."""

    INITIAL = "INITIAL"
    COLLECTING_DATA = "COLLECTING_DATA"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EmploymentType(str, Enum):
    """Modalidad de contratación."""

    INDETERMINATE = "INDETERMINATE"
    FIXED_TERM = "FIXED_TERM"
    TRIAL_PERIOD = "TRIAL_PERIOD"
    PART_TIME = "PART_TIME"


class ValidationSeverity(str, Enum):
    """Severidad de un resultado de validación de campo."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# --------------------------------------------------------------------------- #
# Helpers de validación CUIT / CUIL
# --------------------------------------------------------------------------- #

_CUIT_HYPHENATED_RE = re.compile(r"^\d{2}-\d{8}-\d$")
_CUIT_DIGITS_RE = re.compile(r"^\d{11}$")
_CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def _compute_check_digit(first_ten_digits: str) -> Optional[int]:
    """Calcula el dígito verificador (módulo 11) de un CUIT/CUIL.

    Devuelve ``None`` cuando el resto es 1: no existe dígito válido para esa
    base (AFIP reasigna el prefijo en esos casos).
    """
    total = sum(int(d) * w for d, w in zip(first_ten_digits, _CUIT_WEIGHTS))
    remainder = total % 11
    if remainder == 0:
        return 0
    if remainder == 1:
        return None
    return 11 - remainder


def _normalize_and_check_cuit(value: str, label: str) -> str:
    """Normaliza a ``XX-XXXXXXXX-X`` y valida el dígito verificador.

    Acepta el formato con guiones o 11 dígitos corridos.
    """
    raw = value.strip()
    if _CUIT_HYPHENATED_RE.match(raw):
        digits = raw.replace("-", "")
    elif _CUIT_DIGITS_RE.match(raw):
        digits = raw
    else:
        raise ValueError(f"{label} debe tener el formato XX-XXXXXXXX-X (11 dígitos)")

    expected = _compute_check_digit(digits[:10])
    if expected is None or expected != int(digits[10]):
        raise ValueError(f"{label} con dígito verificador inválido")

    return f"{digits[:2]}-{digits[2:10]}-{digits[10]}"


# --------------------------------------------------------------------------- #
# Sub-modelos de datos
# --------------------------------------------------------------------------- #

_STRICT_CONFIG = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EmployeeData(BaseModel):
    """Datos personales del trabajador."""

    model_config = _STRICT_CONFIG

    nombre: str = Field(
        ..., min_length=1, description="Nombre/s del trabajador.", examples=["Juan Carlos"]
    )
    apellido: str = Field(
        ..., min_length=1, description="Apellido/s del trabajador.", examples=["Pérez"]
    )
    dni: str = Field(
        ...,
        pattern=r"^\d{7,8}$",
        description="DNI: solo dígitos, 7 u 8 caracteres, sin puntos.",
        examples=["30123456"],
    )
    cuil: str = Field(
        ...,
        description=(
            "CUIL en formato XX-XXXXXXXX-X con dígito verificador válido. "
            "Se acepta también sin guiones y se normaliza."
        ),
        examples=["20-30123456-3"],
    )
    domicilio: str = Field(
        ...,
        min_length=1,
        description="Domicilio real del trabajador.",
        examples=["Av. Corrientes 1234, CABA"],
    )
    fecha_nacimiento: date = Field(
        ..., description="Fecha de nacimiento (ISO 8601).", examples=["1985-04-23"]
    )

    @field_validator("cuil")
    @classmethod
    def _validate_cuil(cls, value: str) -> str:
        return _normalize_and_check_cuit(value, "CUIL")

    @model_validator(mode="after")
    def _cuil_matches_dni(self) -> EmployeeData:
        # El CUIL embebe el DNI (rellenado con ceros a 8 dígitos) entre guiones.
        if self.cuil.split("-")[1] != self.dni.zfill(8):
            raise ValueError("El CUIL no coincide con el DNI informado")
        return self


class CompanyData(BaseModel):
    """Datos de la empresa empleadora."""

    model_config = _STRICT_CONFIG

    razon_social: str = Field(
        ..., min_length=1, description="Razón social de la empresa.", examples=["HumanIA S.A."]
    )
    cuit: str = Field(
        ...,
        description=(
            "CUIT en formato XX-XXXXXXXX-X con dígito verificador válido. "
            "Se acepta también sin guiones y se normaliza."
        ),
        examples=["30-71234567-1"],
    )
    domicilio_legal: str = Field(
        ...,
        min_length=1,
        description="Domicilio legal de la empresa.",
        examples=["Av. del Libertador 5000, CABA"],
    )
    apoderado_nombre: str = Field(
        ...,
        min_length=1,
        description="Nombre completo del apoderado que firma por la empresa.",
        examples=["María Gómez"],
    )
    apoderado_cargo: str = Field(
        ..., min_length=1, description="Cargo del apoderado.", examples=["Gerente de RRHH"]
    )

    @field_validator("cuit")
    @classmethod
    def _validate_cuit(cls, value: str) -> str:
        return _normalize_and_check_cuit(value, "CUIT")


class LaborTerms(BaseModel):
    """Condiciones laborales pactadas."""

    model_config = _STRICT_CONFIG

    puesto_funcion: str = Field(
        ..., min_length=1, description="Puesto o función a desempeñar.", examples=["Analista de Datos"]
    )
    fecha_inicio: date = Field(
        ..., description="Fecha de inicio de la relación laboral.", examples=["2026-01-05"]
    )
    modalidad: EmploymentType = Field(
        ..., description="Modalidad de contratación.", examples=["INDETERMINATE"]
    )
    remuneracion_bruta: Decimal = Field(
        ...,
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Remuneración bruta mensual (mayor a 0, hasta 2 decimales).",
        examples=["1500000.00"],
    )
    jornada_laboral: str = Field(
        ...,
        min_length=1,
        description="Jornada laboral en texto libre.",
        examples=["Lunes a Viernes de 09:00 a 18:00 hs"],
    )
    lugar_trabajo: str = Field(
        ...,
        min_length=1,
        description="Lugar donde se prestarán las tareas.",
        examples=["Oficina central, Av. del Libertador 5000, CABA"],
    )


# --------------------------------------------------------------------------- #
# Validación de campo
# --------------------------------------------------------------------------- #


class FieldValidation(BaseModel):
    """Resultado de validar un campo extraído por OCR/LLM."""

    model_config = _STRICT_CONFIG

    field_name: str = Field(
        ...,
        min_length=1,
        description="Ruta del campo validado.",
        examples=["employee.dni"],
    )
    is_valid: bool = Field(..., description="Si el valor pasó la validación.")
    value_extracted: Optional[Any] = Field(
        default=None, description="Valor crudo extraído por el OCR/LLM.", examples=["30123456"]
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confianza de la extracción (0.0 a 1.0).",
        examples=[0.97],
    )
    conflict_detected: bool = Field(
        default=False, description="Si el valor entra en conflicto con otra fuente."
    )
    conflict_detail: Optional[str] = Field(
        default=None,
        description="Descripción del conflicto; obligatoria si conflict_detected es True.",
        examples=["El DNI del documento difiere del declarado en el formulario"],
    )
    severity: ValidationSeverity = Field(
        default=ValidationSeverity.INFO,
        description="Severidad del resultado de la validación.",
        examples=["INFO"],
    )

    @model_validator(mode="after")
    def _conflict_requires_detail(self) -> FieldValidation:
        if self.conflict_detected and not (self.conflict_detail and self.conflict_detail.strip()):
            raise ValueError("conflict_detail es obligatorio cuando conflict_detected es True")
        return self


# --------------------------------------------------------------------------- #
# Modelo principal
# --------------------------------------------------------------------------- #


class ContractData(BaseModel):
    """Single Source of Truth del contrato laboral en construcción."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: UUID = Field(default_factory=uuid4, description="Identificador único del contrato.")
    employee: Optional[EmployeeData] = Field(default=None, description="Datos del trabajador.")
    company: Optional[CompanyData] = Field(default=None, description="Datos de la empresa.")
    terms: Optional[LaborTerms] = Field(default=None, description="Condiciones laborales.")
    validation_flags: List[FieldValidation] = Field(
        default_factory=list, description="Resultados de validación por campo."
    )
    status: ContractStatus = Field(
        default=ContractStatus.INITIAL, description="Estado actual del flujo."
    )
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Campos requeridos aún no cargados (ver get_missing_fields()).",
        examples=[["employee.dni", "terms.puesto_funcion"]],
    )

    # Secciones requeridas -> modelo que las define (para enumerar campos faltantes).
    _REQUIRED_SECTIONS: ClassVar[Dict[str, Type[BaseModel]]] = {
        "employee": EmployeeData,
        "company": CompanyData,
        "terms": LaborTerms,
    }

    def _compute_missing_fields(self) -> List[str]:
        missing: List[str] = []
        for section, model in self._REQUIRED_SECTIONS.items():
            if getattr(self, section) is None:
                missing.extend(f"{section}.{name}" for name in model.model_fields)
        return missing

    def get_missing_fields(self) -> List[str]:
        """Devuelve (y sincroniza en ``missing_fields``) los campos requeridos faltantes.

        Si una sección está ausente se listan todos sus campos con ruta con punto
        (p. ej. ``"employee.dni"``). Una sección presente ya fue validada por
        Pydantic, por lo que sus campos están completos.
        """
        missing = self._compute_missing_fields()
        self.missing_fields = missing
        return list(missing)

    def has_conflicts(self) -> bool:
        """True si algún campo validado reporta un conflicto."""
        return any(flag.conflict_detected for flag in self.validation_flags)

    @property
    def is_complete(self) -> bool:
        """True si todas las secciones están cargadas y ninguna validación falló.

        Una validación cuenta como error si ``is_valid`` es False, su severidad es
        ``ERROR`` o reporta un conflicto.
        """
        if self._compute_missing_fields():
            return False
        return not any(
            (not flag.is_valid)
            or flag.severity is ValidationSeverity.ERROR
            or flag.conflict_detected
            for flag in self.validation_flags
        )

    def mark_as_reviewed(self, approved: bool = True) -> None:
        """Registra la decisión humana sobre el contrato.

        Solo es válido desde ``PENDING_HUMAN_REVIEW``. Aprobar exige que el
        contrato esté completo y sin conflictos.

        Raises:
            ValueError: si el estado actual no es ``PENDING_HUMAN_REVIEW`` o si se
                intenta aprobar un contrato incompleto o con conflictos.
        """
        if self.status is not ContractStatus.PENDING_HUMAN_REVIEW:
            raise ValueError(
                f"Solo se puede revisar un contrato en {ContractStatus.PENDING_HUMAN_REVIEW.value}; "
                f"estado actual: {self.status.value}"
            )
        if approved:
            if self.has_conflicts():
                raise ValueError("No se puede aprobar un contrato con conflictos sin resolver")
            if not self.is_complete:
                raise ValueError("No se puede aprobar un contrato incompleto o con errores")
            self.status = ContractStatus.APPROVED
        else:
            self.status = ContractStatus.REJECTED
