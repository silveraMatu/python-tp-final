"""Catálogo determinista de plantillas disponibles (F02/F08).

La elección de plantilla sale de esta tabla, no del LLM: si una modalidad no
tiene plantilla aprobada, se informa en lugar de improvisar un contrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, List, Mapping, Tuple

from app.schemas.contract import EmploymentType
from app.services.template_service import SUPPORTED_MODALITIES
from app.services.validation_service import FIELD_PATHS

TEMPLATE_FILES: Final[Mapping[EmploymentType, str]] = {
    EmploymentType.INDETERMINATE: "contrato_trabajo_indeterminado.docx",
}

MODALITY_LABELS: Final[Mapping[EmploymentType, str]] = {
    EmploymentType.INDETERMINATE: "Contrato de trabajo por tiempo indeterminado",
    EmploymentType.FIXED_TERM: "Contrato de trabajo a plazo fijo",
    EmploymentType.TRIAL_PERIOD: "Contrato de trabajo a prueba",
    EmploymentType.PART_TIME: "Contrato de trabajo a tiempo parcial",
}


@dataclass(frozen=True)
class TemplateInfo:
    """Descripción de la plantilla disponible (o ausente) para una modalidad."""

    modality: EmploymentType
    label: str
    available: bool
    template_file: str | None
    required_fields: Tuple[str, ...]


def get_template_info(modality: EmploymentType) -> TemplateInfo:
    """Plantilla aprobada para ``modality`` y los campos que exige."""
    template = TEMPLATE_FILES.get(modality)
    available = template is not None and modality in SUPPORTED_MODALITIES
    return TemplateInfo(
        modality=modality,
        label=MODALITY_LABELS[modality],
        available=available,
        template_file=template if available else None,
        required_fields=tuple(sorted(FIELD_PATHS)) if available else (),
    )


def list_templates() -> List[TemplateInfo]:
    """Una entrada por modalidad, disponibles o no."""
    return [get_template_info(modality) for modality in EmploymentType]
