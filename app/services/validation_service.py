"""Motor determinista de validación cruzada (F06).

Decide, sin intervención del LLM, si un dato candidato se acepta, se rechaza o
queda en conflicto a la espera de confirmación humana:

1. Campo desconocido o valor inválido según el esquema  -> ``REJECTED``.
2. Valor distinto del ya aceptado o confianza < umbral    -> ``CONFLICT``.
3. En otro caso                                           -> ``ACCEPTED``.

Además ensambla las secciones (``EmployeeData``, ``CompanyData``, ``LaborTerms``)
a partir de los valores recolectados cuando están todos presentes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, List, Mapping, Optional

from pydantic import BaseModel, ValidationError

from app.schemas.contract import (
    CompanyData,
    ContractData,
    EmployeeData,
    FieldValidation,
    LaborTerms,
    ValidationSeverity,
)
from app.schemas.extraction import FieldCandidate

SECTION_MODELS: Final[Mapping[str, type[BaseModel]]] = MappingProxyType(
    {"employee": EmployeeData, "company": CompanyData, "terms": LaborTerms}
)
FIELD_PATHS: Final[frozenset[str]] = frozenset(
    f"{section}.{name}" for section, model in SECTION_MODELS.items() for name in model.model_fields
)

_DIGITS_ONLY_FIELDS: Final[frozenset[str]] = frozenset({"dni", "cuil", "cuit"})
_ERROR_PREFIX_RE: Final[re.Pattern[str]] = re.compile(r"^Value error, ")
_MISSING: Final[object] = object()


class Outcome(str, Enum):
    """Resultado de evaluar un dato candidato."""

    ACCEPTED = "ACCEPTED"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class CandidateEvaluation:
    """Veredicto sobre un candidato junto con el flag de validación resultante."""

    candidate: FieldCandidate
    outcome: Outcome
    flag: FieldValidation
    unchanged: bool = False  # ACCEPTED y ya coincide con el valor guardado

    @property
    def reason(self) -> Optional[str]:
        return self.flag.conflict_detail if self.outcome is not Outcome.ACCEPTED else None


@dataclass(frozen=True)
class AssemblyResult:
    """Secciones ensambladas (``None`` si aún incompletas o inválidas) y errores por sección."""

    sections: Mapping[str, Optional[BaseModel]]
    errors: Mapping[str, str] = field(default_factory=dict)


def accepted_flag(path: str, value: Any, confidence: float = 1.0) -> FieldValidation:
    """Flag de un valor aceptado y sin conflicto."""
    return FieldValidation(
        field_name=path,
        is_valid=True,
        value_extracted=value,
        confidence_score=confidence,
        conflict_detected=False,
        severity=ValidationSeverity.INFO,
    )


def _clean(message: str) -> str:
    return _ERROR_PREFIX_RE.sub("", message)


class ValidationService:
    """Reglas de validación puras (no persisten ni mutan el contrato)."""

    def __init__(self, confidence_threshold: float = 0.80) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold debe estar entre 0.0 y 1.0")
        self._threshold = confidence_threshold

    @property
    def confidence_threshold(self) -> float:
        return self._threshold

    # ------------------------------------------------------------------ #
    # Evaluación de candidatos
    # ------------------------------------------------------------------ #

    def evaluate(self, contract: ContractData, candidate: FieldCandidate) -> CandidateEvaluation:
        """Evalúa un candidato contra los valores ya recolectados del contrato."""
        path = candidate.field_name
        if path not in FIELD_PATHS:
            return self._rejected(candidate, [f"Campo no reconocido: {path}"])

        errors = self.field_errors(contract, path, candidate.value)
        if errors:
            return self._rejected(candidate, errors)

        previous = contract.collected_values.get(path, _MISSING)
        differs = previous is not _MISSING and self._canonical(path, previous) != self._canonical(
            path, candidate.value
        )
        if previous is not _MISSING and not differs:
            return CandidateEvaluation(
                candidate,
                Outcome.ACCEPTED,
                accepted_flag(path, candidate.value, candidate.confidence_score),
                unchanged=True,
            )

        reasons: List[str] = []
        if differs:
            reasons.append(
                f"El valor nuevo '{candidate.value}' difiere del valor previo '{previous}'"
            )
        if candidate.confidence_score < self._threshold:
            reasons.append(
                f"Confianza {candidate.confidence_score:.2f} por debajo del umbral "
                f"{self._threshold:.2f}"
            )
        if reasons:
            flag = FieldValidation(
                field_name=path,
                is_valid=True,
                value_extracted=candidate.value,
                confidence_score=candidate.confidence_score,
                conflict_detected=True,
                conflict_detail="; ".join(reasons),
                severity=ValidationSeverity.WARNING,
            )
            return CandidateEvaluation(candidate, Outcome.CONFLICT, flag)

        return CandidateEvaluation(
            candidate,
            Outcome.ACCEPTED,
            accepted_flag(path, candidate.value, candidate.confidence_score),
        )

    def field_errors(self, contract: ContractData, path: str, value: Any) -> List[str]:
        """Errores de formato/validador del valor, validando solo ese campo.

        Se valida el modelo de la sección con los valores ya recolectados más el
        candidato; los errores ``missing`` (otros campos aún no cargados) y los de
        nivel modelo (cruces entre campos) se ignoran: estos últimos los reporta
        :meth:`assemble` cuando la sección está completa.
        """
        section, name = path.split(".", 1)
        values = self._section_values(contract.collected_values, section)
        values[name] = value
        try:
            SECTION_MODELS[section].model_validate(values)
        except ValidationError as exc:
            return [
                _clean(err["msg"])
                for err in exc.errors()
                if err["type"] != "missing" and err["loc"] and err["loc"][0] == name
            ]
        return []

    # ------------------------------------------------------------------ #
    # Ensamblado de secciones
    # ------------------------------------------------------------------ #

    def assemble(self, collected_values: Mapping[str, Any]) -> AssemblyResult:
        """Construye cada sección cuyos campos estén todos presentes."""
        sections: dict[str, Optional[BaseModel]] = {}
        errors: dict[str, str] = {}
        for section, model in SECTION_MODELS.items():
            values = self._section_values(collected_values, section)
            sections[section] = None
            if set(values) != set(model.model_fields):
                continue
            try:
                sections[section] = model.model_validate(values)
            except ValidationError as exc:
                errors[section] = "; ".join(_clean(err["msg"]) for err in exc.errors())
        return AssemblyResult(sections=sections, errors=errors)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _section_values(collected_values: Mapping[str, Any], section: str) -> dict[str, Any]:
        prefix = f"{section}."
        return {
            path[len(prefix) :]: value
            for path, value in collected_values.items()
            if path.startswith(prefix)
        }

    @staticmethod
    def _rejected(candidate: FieldCandidate, errors: List[str]) -> CandidateEvaluation:
        flag = FieldValidation(
            field_name=candidate.field_name,
            is_valid=False,
            value_extracted=candidate.value,
            confidence_score=candidate.confidence_score,
            conflict_detected=False,
            conflict_detail="; ".join(errors),
            severity=ValidationSeverity.ERROR,
        )
        return CandidateEvaluation(candidate, Outcome.REJECTED, flag)

    @staticmethod
    def _canonical(path: str, value: Any) -> object:
        """Forma normalizada para comparar valores sin falsos conflictos (formato, mayúsculas)."""
        section, name = path.split(".", 1)
        if name in _DIGITS_ONLY_FIELDS:
            return re.sub(r"\D", "", str(value))
        annotation = SECTION_MODELS[section].model_fields[name].annotation
        if annotation is date:
            return value.isoformat() if isinstance(value, date) else str(value).strip()
        if annotation is Decimal:
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return str(value)
        if isinstance(value, Enum):
            return str(value.value).strip().upper()
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return str(value).strip().upper()
        return " ".join(str(value).split()).casefold()
