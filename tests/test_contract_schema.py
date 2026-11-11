from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.contract import (
    CompanyData,
    ContractData,
    ContractStatus,
    EmployeeData,
    FieldValidation,
    LaborTerms,
    ValidationSeverity,
)
from tests.conftest import VALID_CUIL, VALID_CUIT


def _employee(**overrides: object) -> EmployeeData:
    data: dict[str, object] = {
        "nombre": "Juan",
        "apellido": "Pérez",
        "dni": "30123456",
        "cuil": VALID_CUIL,
        "domicilio": "X 1",
        "fecha_nacimiento": date(1995, 3, 15),
    }
    data.update(overrides)
    return EmployeeData(**data)  # type: ignore[arg-type]


def test_cuil_without_hyphens_is_normalized() -> None:
    assert _employee(cuil=VALID_CUIL.replace("-", "")).cuil == VALID_CUIL


@pytest.mark.parametrize("cuil", ["20-30123456-4", "20-3012345-66", "ab-30123456-3", "2030123456"])
def test_invalid_cuil_is_rejected(cuil: str) -> None:
    with pytest.raises(ValidationError):
        _employee(cuil=cuil)


@pytest.mark.parametrize("dni", ["123456", "123456789", "12a45678"])
def test_invalid_dni_is_rejected(dni: str) -> None:
    with pytest.raises(ValidationError):
        _employee(dni=dni)


def test_cuil_must_match_dni() -> None:
    with pytest.raises(ValidationError, match="no coincide"):
        _employee(dni="30123457")


def test_company_cuit_check_digit() -> None:
    with pytest.raises(ValidationError):
        CompanyData(
            razon_social="x",
            cuit="30-71234567-0",
            domicilio_legal="a",
            apoderado_nombre="a",
            apoderado_cargo="a",
        )
    assert VALID_CUIT


@pytest.mark.parametrize("salary", [Decimal("0"), Decimal("-1"), Decimal("1.234")])
def test_invalid_salary_is_rejected(salary: Decimal, terms: LaborTerms) -> None:
    with pytest.raises(ValidationError):
        LaborTerms(**{**terms.model_dump(), "remuneracion_bruta": salary})


def test_extra_fields_are_forbidden(employee: EmployeeData) -> None:
    with pytest.raises(ValidationError):
        EmployeeData.model_validate({**employee.model_dump(), "inventado": 1})


def test_conflict_requires_detail() -> None:
    with pytest.raises(ValidationError):
        FieldValidation(
            field_name="a", is_valid=True, confidence_score=0.5, conflict_detected=True
        )
    with pytest.raises(ValidationError):
        FieldValidation(field_name="a", is_valid=True, confidence_score=1.2)


def test_empty_contract_is_incomplete() -> None:
    empty = ContractData()
    assert not empty.is_complete
    assert len(empty.get_missing_fields()) == 17
    assert empty.missing_fields == empty.get_missing_fields()


def test_complete_contract_and_error_flag(contract: ContractData) -> None:
    assert contract.is_complete
    contract.validation_flags.append(
        FieldValidation(
            field_name="a", is_valid=True, confidence_score=0.9, severity=ValidationSeverity.ERROR
        )
    )
    assert not contract.is_complete


def test_mark_as_reviewed_guards(contract: ContractData) -> None:
    with pytest.raises(ValueError):
        contract.mark_as_reviewed()  # estado INITIAL

    contract.status = ContractStatus.PENDING_HUMAN_REVIEW
    contract.validation_flags.append(
        FieldValidation(
            field_name="a",
            is_valid=True,
            confidence_score=0.9,
            conflict_detected=True,
            conflict_detail="difiere",
        )
    )
    with pytest.raises(ValueError):
        contract.mark_as_reviewed()

    contract.validation_flags.clear()
    contract.mark_as_reviewed()
    assert contract.status is ContractStatus.APPROVED


def test_reject_and_roundtrip(contract: ContractData) -> None:
    contract.status = ContractStatus.PENDING_HUMAN_REVIEW
    contract.mark_as_reviewed(approved=False)
    assert contract.status is ContractStatus.REJECTED
    assert ContractData.model_validate(contract.model_dump()) == contract
    assert ContractData.model_validate_json(contract.model_dump_json()) == contract
