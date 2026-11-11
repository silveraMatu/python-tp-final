"""Puerto de persistencia de contratos."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.contract import ContractData, ContractStatus


class AuditEntry(BaseModel):
    """Registro inmutable de un cambio sobre un contrato."""

    model_config = ConfigDict(frozen=True)

    id: int
    contract_id: UUID
    timestamp: datetime
    actor: str
    action: str
    status: ContractStatus
    detail: Optional[str] = None


class ContractRepository(Protocol):
    """Contrato que debe cumplir cualquier adaptador de persistencia."""

    def create(self, contract: ContractData, actor: str) -> None:
        """Persiste un contrato nuevo.

        Raises:
            ContractAlreadyExistsError: el id ya existe.
        """
        ...

    def get(self, contract_id: UUID) -> ContractData:
        """Devuelve el contrato.

        Raises:
            ContractNotFoundError: no existe.
        """
        ...

    def save(
        self,
        contract: ContractData,
        actor: str,
        action: str,
        detail: Optional[str] = None,
    ) -> None:
        """Actualiza el contrato y registra la auditoría en una sola transacción.

        Raises:
            ContractNotFoundError: no existe.
        """
        ...

    def list(self, status: Optional[ContractStatus] = None) -> List[ContractData]:
        """Lista los contratos (opcionalmente filtrados por estado), del más antiguo al más nuevo."""
        ...

    def history(self, contract_id: UUID) -> List[AuditEntry]:
        """Auditoría del contrato en orden cronológico.

        Raises:
            ContractNotFoundError: no existe.
        """
        ...
