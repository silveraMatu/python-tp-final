"""Revisión humana (HITL): solo un revisor aprueba, rechaza o pide cambios."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api import access
from app.api.deps import LocksDep, ReviewerDep, ServicesDep
from app.api.presenters import contract_out
from app.api.schemas import ContractOut, ReviewIn

router = APIRouter(prefix="/contracts", tags=["revisión"])


@router.post("/{contract_id}/review", response_model=ContractOut)
def review_contract(
    contract_id: UUID,
    body: ReviewIn,
    user: ReviewerDep,
    services: ServicesDep,
    locks: LocksDep,
) -> ContractOut:
    """Registra la decisión del revisor sobre un contrato pendiente de revisión.

    - ``APPROVE``: aprueba (el documento final se emite al descargarlo).
    - ``REJECT``: rechaza; el contrato queda cerrado.
    - ``REQUEST_CHANGES``: lo devuelve al solicitante para completar o corregir datos.
    """
    access.load_visible(services, user, contract_id)
    with locks.hold(contract_id):
        if body.decision == "REQUEST_CHANGES":
            contract = services.contracts.request_changes(contract_id, user.name, body.comment)
        else:
            contract = services.contracts.review(
                contract_id, body.decision == "APPROVE", user.name, body.comment
            )
    return contract_out(contract, user)
