"""Textos de respuesta del agente, construidos de forma determinista desde el estado.

Ningún texto sobre el contrato lo escribe el LLM: todo sale de plantillas fijas y
de los valores validados del ``ContractData``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Final, List, Optional

from app.schemas.contract import ContractData, ContractStatus, FieldValidation
from app.schemas.contract import EmploymentType
from app.services.template_catalog import MODALITY_LABELS
from app.services.template_service import format_ars, format_date, format_dni

FIELD_LABELS: Final[Dict[str, str]] = {
    "employee.nombre": "Nombre del empleado/a",
    "employee.apellido": "Apellido del empleado/a",
    "employee.dni": "DNI del empleado/a",
    "employee.cuil": "CUIL del empleado/a",
    "employee.domicilio": "Domicilio del empleado/a",
    "employee.fecha_nacimiento": "Fecha de nacimiento del empleado/a",
    "company.razon_social": "Razón social de la empresa",
    "company.cuit": "CUIT de la empresa",
    "company.domicilio_legal": "Domicilio legal de la empresa",
    "company.apoderado_nombre": "Nombre del apoderado",
    "company.apoderado_cargo": "Cargo del apoderado",
    "terms.puesto_funcion": "Puesto o función",
    "terms.fecha_inicio": "Fecha de inicio",
    "terms.modalidad": "Modalidad de contratación",
    "terms.remuneracion_bruta": "Remuneración bruta mensual",
    "terms.jornada_laboral": "Jornada laboral",
    "terms.lugar_trabajo": "Lugar de prestación de servicios",
}

SECTION_LABELS: Final[Dict[str, str]] = {
    "employee": "datos del empleado/a",
    "company": "datos de la empresa",
    "terms": "condiciones laborales",
}

STATUS_LABELS: Final[Dict[ContractStatus, str]] = {
    ContractStatus.INITIAL: "Nuevo (sin datos)",
    ContractStatus.COLLECTING_DATA: "Recolectando datos",
    ContractStatus.CONFLICT_DETECTED: "Esperando tu confirmación de un dato",
    ContractStatus.PENDING_HUMAN_REVIEW: "Pendiente de revisión humana",
    ContractStatus.APPROVED: "Aprobado",
    ContractStatus.REJECTED: "Rechazado",
}

WELCOME: Final[str] = (
    "Hola, soy el asistente de contratos de HumanIA. Puedo armar un contrato de trabajo por "
    "tiempo indeterminado: contame los datos o adjuntá el DNI, un formulario o un PDF y yo "
    "los voy ordenando. También respondo consultas sobre las cláusulas aprobadas."
)
NOT_UNDERSTOOD: Final[str] = (
    "No estoy seguro de qué necesitás. Podés darme datos del contrato, adjuntar un documento, "
    "preguntarme por las cláusulas, pedir el estado o el borrador."
)
NO_PENDING_CONFLICT: Final[str] = "No hay ningún dato pendiente de confirmación."
CONFIRMATION_UNCLEAR: Final[str] = (
    "No entendí si querés usar el valor nuevo o mantener el anterior. "
    "Respondé «sí» para usar el nuevo o «no» para mantener el anterior."
)
NO_DATA_FOUND: Final[str] = "No encontré datos del contrato en tu mensaje."
RAG_UNAVAILABLE: Final[str] = "La consulta de documentación no está disponible en este momento."
SECURITY_REFUSAL: Final[str] = (
    "No puedo procesar ese mensaje: incluye instrucciones que intentan cambiar mi funcionamiento "
    "o pedir información interna, y no las voy a seguir. Si querés cargar datos del contrato, "
    "escribilos de forma simple (por ejemplo: «El empleado se llama Juan Pérez, DNI 30123456»)."
)
DOCUMENT_DISCARDED: Final[str] = (
    "Descarté «{name}» porque su contenido incluye instrucciones sospechosas. Si es un documento "
    "legítimo, revisalo y volvé a subirlo."
)
LOCKED_PENDING: Final[str] = (
    "El contrato está en revisión humana y no admite cambios; si el revisor pide ajustes, "
    "se reabre para completar datos."
)
LOCKED_CLOSED: Final[str] = "El contrato ya está cerrado ({status}) y no admite cambios."


def label(path: str) -> str:
    """Etiqueta legible de un campo (o la ruta si no se conoce)."""
    return FIELD_LABELS.get(path, SECTION_LABELS.get(path, path))


def display_value(path: str, value: Any) -> str:
    """Valor formateado para mostrar al usuario (es-AR)."""
    text = str(value)
    name = path.split(".", 1)[-1]
    try:
        if name in {"fecha_nacimiento", "fecha_inicio"}:
            return format_date(value if isinstance(value, date) else date.fromisoformat(text))
        if name == "remuneracion_bruta":
            return format_ars(Decimal(text))
        if name == "dni":
            return format_dni(text)
        if name in {"cuil", "cuit"}:
            digits = "".join(ch for ch in text if ch.isdigit())
            return f"{digits[:2]}-{digits[2:10]}-{digits[10]}" if len(digits) == 11 else text
        if name == "modalidad":
            return MODALITY_LABELS[EmploymentType(text)]
    except (ValueError, KeyError, InvalidOperation):
        return text
    return text


def pending_conflicts(contract: ContractData) -> List[FieldValidation]:
    """Flags con confirmación pendiente, en orden de llegada."""
    return [flag for flag in contract.validation_flags if flag.conflict_detected]


def conflict_prompt(contract: ContractData) -> Optional[str]:
    """Pregunta de confirmación por el primer conflicto pendiente (uno por vez)."""
    conflicts = pending_conflicts(contract)
    if not conflicts:
        return None
    flag = conflicts[0]
    path = flag.field_name
    lines = [
        f"Necesito que confirmes un dato: {label(path)}.",
        f"- Valor leído: {display_value(path, flag.value_extracted)}",
    ]
    if path in contract.collected_values:
        lines.append(f"- Valor anterior: {display_value(path, contract.collected_values[path])}")
    if flag.conflict_detail:
        lines.append(f"- Motivo: {flag.conflict_detail}")
    lines.append("¿Usamos el valor leído? Respondé «sí» para usarlo o «no» para descartarlo.")
    if len(conflicts) > 1:
        lines.append(f"(Quedan {len(conflicts) - 1} dato(s) más por confirmar.)")
    return "\n".join(lines)


def missing_prompt(contract: ContractData, limit: int = 5) -> Optional[str]:
    """Lista de datos que faltan, agrupados por sección (máximo ``limit`` por mensaje)."""
    missing = contract.get_missing_fields()
    if not missing:
        return None
    shown = missing[:limit]
    lines = [f"Me faltan {len(missing)} dato(s). Por ahora necesito:"]
    lines.extend(f"- {label(path)}" for path in shown)
    if len(missing) > limit:
        lines.append(f"(y {len(missing) - limit} más después)")
    return "\n".join(lines)


def summary(contract: ContractData) -> str:
    """Resumen de lo cargado y de lo que falta."""
    total = len(FIELD_LABELS)
    collected = [path for path in FIELD_LABELS if path in contract.collected_values]
    lines = [
        f"Estado: {STATUS_LABELS[contract.status]}. Datos cargados: {len(collected)}/{total}."
    ]
    lines.extend(
        f"- {label(path)}: {display_value(path, contract.collected_values[path])}"
        for path in collected
    )
    return "\n".join(lines)


def section_errors(contract: ContractData) -> List[str]:
    """Inconsistencias entre campos de una misma sección (p. ej. CUIL y DNI)."""
    return [
        f"Hay una inconsistencia en los {SECTION_LABELS[flag.field_name]}: {flag.conflict_detail}"
        for flag in contract.validation_flags
        if flag.field_name in SECTION_LABELS and not flag.is_valid
    ]


def next_step(contract: ContractData) -> str:
    """Qué sigue, según el estado del contrato."""
    status = contract.status
    if status is ContractStatus.PENDING_HUMAN_REVIEW:
        return "El borrador está pendiente de revisión humana; no puedo aprobarlo yo."
    if status in (ContractStatus.APPROVED, ContractStatus.REJECTED):
        return LOCKED_CLOSED.format(status=STATUS_LABELS[status].lower())

    prompt = conflict_prompt(contract)
    if prompt:
        return prompt
    errors = section_errors(contract)
    if errors:
        return "\n".join([*errors, "Corregí alguno de los dos datos para continuar."])
    missing = missing_prompt(contract)
    if missing:
        return missing
    if contract.is_complete:
        return (
            "Tengo todos los datos. Podés pedirme «ver borrador» para la versión preliminar o "
            "«enviar a revisión» para que lo revise una persona."
        )
    return "Revisá los datos marcados con error antes de continuar."
