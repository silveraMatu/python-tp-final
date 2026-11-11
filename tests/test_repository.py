from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.exceptions import ContractAlreadyExistsError, ContractNotFoundError
from app.repositories.sqlite import SqliteContractRepository
from app.schemas.contract import ContractData, ContractStatus


@pytest.fixture
def repo(tmp_path: Path) -> SqliteContractRepository:
    return SqliteContractRepository(tmp_path / "nested" / "contracts.db")


def test_create_and_get_roundtrip(repo: SqliteContractRepository, contract: ContractData) -> None:
    contract.collected_values["employee.dni"] = "30123456"
    repo.create(contract, "ana")
    assert repo.get(contract.id) == contract


def test_create_duplicate_is_rejected(
    repo: SqliteContractRepository, contract: ContractData
) -> None:
    repo.create(contract, "ana")
    with pytest.raises(ContractAlreadyExistsError):
        repo.create(contract, "ana")


def test_get_and_save_unknown_contract(repo: SqliteContractRepository) -> None:
    with pytest.raises(ContractNotFoundError):
        repo.get(uuid4())
    with pytest.raises(ContractNotFoundError):
        repo.save(ContractData(), "ana", "x")
    with pytest.raises(ContractNotFoundError):
        repo.history(uuid4())


def test_save_updates_and_audits(repo: SqliteContractRepository, contract: ContractData) -> None:
    repo.create(contract, "ana")
    contract.status = ContractStatus.COLLECTING_DATA
    repo.save(contract, "bruno", "extraction_applied", "aceptados=2")

    assert repo.get(contract.id).status is ContractStatus.COLLECTING_DATA
    history = repo.history(contract.id)
    assert [(h.actor, h.action, h.status) for h in history] == [
        ("ana", "created", ContractStatus.INITIAL),
        ("bruno", "extraction_applied", ContractStatus.COLLECTING_DATA),
    ]
    assert history[1].detail == "aceptados=2"
    assert history[0].timestamp <= history[1].timestamp


def test_list_filters_by_status(repo: SqliteContractRepository) -> None:
    first, second = ContractData(), ContractData(status=ContractStatus.COLLECTING_DATA)
    repo.create(first, "ana")
    repo.create(second, "ana")
    assert [c.id for c in repo.list()] == [first.id, second.id]
    assert [c.id for c in repo.list(ContractStatus.COLLECTING_DATA)] == [second.id]
