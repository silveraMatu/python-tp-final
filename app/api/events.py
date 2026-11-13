"""Textos de los mensajes de sistema que se anotan en el chat del solicitante."""

from __future__ import annotations

from typing import Optional

from app.agent import replies
from app.schemas.contract import ContractData


def conflict_resolved(contract: ContractData, field_name: str, accepted: bool) -> str:
    """Confirmación o descarte de un dato pendiente (usa el estado previo del contrato)."""
    flag = next(
        (f for f in replies.pending_conflicts(contract) if f.field_name == field_name), None
    )
    label = replies.label(field_name)
    if accepted and flag is not None:
        return f"Confirmaste «{label}»: {replies.display_value(field_name, flag.value_extracted)}."
    if accepted:
        return f"Confirmaste «{label}»."
    return f"Descartaste el valor leído para «{label}»."


def submitted() -> str:
    return "Enviaste el borrador a revisión humana."


def reviewed(reviewer: str, decision: str, comment: Optional[str]) -> str:
    """Decisión del revisor, con su comentario si lo dejó."""
    action = {
        "APPROVE": "aprobó el contrato",
        "REJECT": "rechazó el contrato",
        "REQUEST_CHANGES": "pidió cambios en el borrador",
    }[decision]
    text = f"El revisor {reviewer} {action}."
    if comment and comment.strip():
        text += f" Comentario: «{comment.strip()}»"
    return text
