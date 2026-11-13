"""Reglas de acceso a contratos según el rol y la propiedad."""

from __future__ import annotations

from uuid import UUID

from app.api.auth import ApiUser, Role
from app.container import Services
from app.core.exceptions import ContractNotFoundError
from app.schemas.contract import ContractData, ContractStatus

# El revisor ve los contratos que llegaron a revisión o ya tuvieron decisión.
REVIEWER_VISIBLE = frozenset(
    {ContractStatus.PENDING_HUMAN_REVIEW, ContractStatus.APPROVED, ContractStatus.REJECTED}
)
EDITABLE = frozenset(
    {ContractStatus.INITIAL, ContractStatus.COLLECTING_DATA, ContractStatus.CONFLICT_DETECTED}
)


def can_view(user: ApiUser, contract: ContractData) -> bool:
    """El solicitante ve los suyos; el revisor, los que están o pasaron por revisión."""
    if user.role is Role.REQUESTER:
        return contract.created_by == user.name
    return contract.status in REVIEWER_VISIBLE


def load_visible(services: Services, user: ApiUser, contract_id: UUID) -> ContractData:
    """Carga el contrato; si el usuario no puede verlo responde como si no existiera (404)."""
    contract = services.contracts.get(contract_id)
    if not can_view(user, contract):
        raise ContractNotFoundError(str(contract_id))
    return contract


def load_owned(services: Services, user: ApiUser, contract_id: UUID) -> ContractData:
    """Contrato propio de un solicitante (para modificarlo)."""
    contract = load_visible(services, user, contract_id)
    if user.role is not Role.REQUESTER or contract.created_by != user.name:
        raise ContractNotFoundError(str(contract_id))
    return contract
