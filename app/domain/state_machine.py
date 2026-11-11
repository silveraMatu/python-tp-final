"""Máquina de estados del borrador de contrato.

Es la única fuente de verdad sobre qué transiciones de :class:`ContractStatus`
son válidas. Los servicios cambian el estado a través de :func:`transition`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from app.core.exceptions import InvalidStateTransitionError
from app.schemas.contract import ContractData, ContractStatus

ALLOWED_TRANSITIONS: Mapping[ContractStatus, frozenset[ContractStatus]] = MappingProxyType(
    {
        ContractStatus.INITIAL: frozenset({ContractStatus.COLLECTING_DATA}),
        ContractStatus.COLLECTING_DATA: frozenset(
            {ContractStatus.CONFLICT_DETECTED, ContractStatus.PENDING_HUMAN_REVIEW}
        ),
        ContractStatus.CONFLICT_DETECTED: frozenset({ContractStatus.COLLECTING_DATA}),
        ContractStatus.PENDING_HUMAN_REVIEW: frozenset(
            {
                ContractStatus.APPROVED,
                ContractStatus.REJECTED,
                ContractStatus.COLLECTING_DATA,  # el revisor pide cambios
            }
        ),
        ContractStatus.APPROVED: frozenset(),
        ContractStatus.REJECTED: frozenset(),
    }
)

TERMINAL_STATES: frozenset[ContractStatus] = frozenset(
    state for state, targets in ALLOWED_TRANSITIONS.items() if not targets
)


def can_transition(current: ContractStatus, target: ContractStatus) -> bool:
    """True si ``current -> target`` figura en la tabla de transiciones."""
    return target in ALLOWED_TRANSITIONS[current]


def transition(contract: ContractData, target: ContractStatus) -> ContractStatus:
    """Mueve ``contract`` a ``target`` validando la tabla y las guardas de negocio.

    Guardas:
    - Entrar a ``PENDING_HUMAN_REVIEW`` exige contrato completo y sin conflictos.
    - Entrar a ``CONFLICT_DETECTED`` exige que exista al menos un conflicto.
    - ``APPROVED`` solo se alcanza vía ``ContractData.mark_as_reviewed``, que
      aplica sus propias guardas; aquí se bloquea para evitar atajos.

    Returns:
        El estado anterior.

    Raises:
        InvalidStateTransitionError: transición o guarda no satisfecha.
    """
    current = contract.status
    if not can_transition(current, target):
        raise InvalidStateTransitionError(current.value, target.value)

    if target is ContractStatus.APPROVED:
        raise InvalidStateTransitionError(
            current.value, target.value, "la aprobación se realiza con mark_as_reviewed()"
        )
    if target is ContractStatus.CONFLICT_DETECTED and not contract.has_conflicts():
        raise InvalidStateTransitionError(
            current.value, target.value, "no hay conflictos registrados"
        )
    if target is ContractStatus.PENDING_HUMAN_REVIEW:
        if contract.has_conflicts():
            raise InvalidStateTransitionError(
                current.value, target.value, "hay conflictos sin resolver"
            )
        if not contract.is_complete:
            raise InvalidStateTransitionError(
                current.value, target.value, "el contrato está incompleto o tiene errores"
            )

    contract.status = target
    return current
