"""Excepciones de dominio del Agente de Contratos Laborales (HumanIA S.A.).

Todas heredan de :class:`HumanIAError` para que las capas superiores (API,
agente) puedan capturarlas de forma uniforme y mapearlas a respuestas claras.
"""

from __future__ import annotations

from collections.abc import Sequence


class HumanIAError(Exception):
    """Base de todas las excepciones de dominio."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class IncompleteContractDataError(HumanIAError):
    """El contrato no está completo o tiene validaciones con error/conflicto."""

    def __init__(
        self,
        missing_fields: Sequence[str] = (),
        invalid_fields: Sequence[str] = (),
    ) -> None:
        self.missing_fields: list[str] = list(missing_fields)
        self.invalid_fields: list[str] = list(invalid_fields)
        parts: list[str] = []
        if self.missing_fields:
            parts.append(f"campos faltantes: {', '.join(self.missing_fields)}")
        if self.invalid_fields:
            parts.append(f"campos con errores o conflictos: {', '.join(self.invalid_fields)}")
        detail = "; ".join(parts) if parts else "el contrato no está completo"
        super().__init__(f"Datos del contrato incompletos ({detail})")


class TemplateNotFoundError(HumanIAError):
    """La plantilla .docx solicitada no existe."""

    def __init__(self, template_path: str) -> None:
        self.template_path = template_path
        super().__init__(f"No se encontró la plantilla de contrato: {template_path}")


class ContractRenderError(HumanIAError):
    """Falló la generación o la verificación del documento del contrato."""


class UnsupportedModalityError(HumanIAError):
    """No hay una plantilla aprobada para la modalidad de contratación pedida."""

    def __init__(self, modality: str) -> None:
        self.modality = modality
        super().__init__(f"No hay una plantilla aprobada para la modalidad {modality}")


class InvalidStateTransitionError(HumanIAError):
    """Se intentó una transición de estado no permitida."""

    def __init__(self, current: str, target: str, reason: str | None = None) -> None:
        self.current = current
        self.target = target
        message = f"Transición de estado no permitida: {current} -> {target}"
        if reason:
            message = f"{message} ({reason})"
        super().__init__(message)


class ContractNotFoundError(HumanIAError):
    """No existe un contrato con el identificador indicado."""

    def __init__(self, contract_id: str) -> None:
        self.contract_id = contract_id
        super().__init__(f"No se encontró el contrato {contract_id}")
