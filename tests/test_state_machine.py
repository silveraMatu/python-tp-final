from __future__ import annotations

import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.domain.state_machine import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    can_transition,
    transition,
)
from app.schemas.contract import ContractData, ContractStatus, FieldValidation


def test_every_state_has_an_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(ContractStatus)
    assert TERMINAL_STATES == {ContractStatus.APPROVED, ContractStatus.REJECTED}


def test_happy_path(contract: ContractData) -> None:
    assert transition(contract, ContractStatus.COLLECTING_DATA) is ContractStatus.INITIAL
    transition(contract, ContractStatus.PENDING_HUMAN_REVIEW)
    assert contract.status is ContractStatus.PENDING_HUMAN_REVIEW
    contract.mark_as_reviewed()
    assert contract.status is ContractStatus.APPROVED


def test_invalid_transition_is_rejected() -> None:
    contract = ContractData()
    with pytest.raises(InvalidStateTransitionError):
        transition(contract, ContractStatus.PENDING_HUMAN_REVIEW)
    assert contract.status is ContractStatus.INITIAL
    assert not can_transition(ContractStatus.APPROVED, ContractStatus.COLLECTING_DATA)


def test_incomplete_contract_cannot_go_to_review() -> None:
    contract = ContractData(status=ContractStatus.COLLECTING_DATA)
    with pytest.raises(InvalidStateTransitionError, match="incompleto"):
        transition(contract, ContractStatus.PENDING_HUMAN_REVIEW)


def test_conflict_cycle(contract: ContractData) -> None:
    contract.status = ContractStatus.COLLECTING_DATA
    with pytest.raises(InvalidStateTransitionError, match="no hay conflictos"):
        transition(contract, ContractStatus.CONFLICT_DETECTED)

    contract.validation_flags.append(
        FieldValidation(
            field_name="employee.dni",
            is_valid=True,
            confidence_score=0.4,
            conflict_detected=True,
            conflict_detail="El DNI de la foto difiere del escrito",
        )
    )
    transition(contract, ContractStatus.CONFLICT_DETECTED)
    with pytest.raises(InvalidStateTransitionError):
        transition(contract, ContractStatus.PENDING_HUMAN_REVIEW)

    contract.validation_flags.clear()
    transition(contract, ContractStatus.COLLECTING_DATA)


def test_approval_only_via_mark_as_reviewed(contract: ContractData) -> None:
    contract.status = ContractStatus.PENDING_HUMAN_REVIEW
    with pytest.raises(InvalidStateTransitionError, match="mark_as_reviewed"):
        transition(contract, ContractStatus.APPROVED)
