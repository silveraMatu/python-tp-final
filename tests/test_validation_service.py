from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.contract import ContractData, EmploymentType, ValidationSeverity
from app.schemas.extraction import FieldCandidate
from app.services.validation_service import FIELD_PATHS, Outcome, ValidationService
from tests.conftest import VALID_CUIL


@pytest.fixture
def validator() -> ValidationService:
    return ValidationService(confidence_threshold=0.8)


def candidate(path: str, value: object, confidence: float = 0.95) -> FieldCandidate:
    return FieldCandidate(field_name=path, value=value, confidence_score=confidence)


def test_field_paths_cover_all_sections() -> None:
    assert len(FIELD_PATHS) == 17
    assert "employee.dni" in FIELD_PATHS and "terms.remuneracion_bruta" in FIELD_PATHS


def test_invalid_threshold() -> None:
    with pytest.raises(ValueError):
        ValidationService(confidence_threshold=1.5)


def test_unknown_field_is_rejected(validator: ValidationService) -> None:
    result = validator.evaluate(ContractData(), candidate("employee.salario", "1"))
    assert result.outcome is Outcome.REJECTED
    assert "no reconocido" in (result.reason or "")
    assert result.flag.severity is ValidationSeverity.ERROR and not result.flag.is_valid


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("employee.dni", "12ab"),
        ("employee.cuil", "20-30123456-4"),
        ("company.cuit", "30-71234567-0"),
        ("terms.remuneracion_bruta", "-5"),
        ("terms.modalidad", "FREELANCE"),
        ("employee.fecha_nacimiento", "no es fecha"),
    ],
)
def test_invalid_values_are_rejected(validator: ValidationService, path: str, value: str) -> None:
    result = validator.evaluate(ContractData(), candidate(path, value))
    assert result.outcome is Outcome.REJECTED
    assert result.reason


def test_valid_value_is_accepted(validator: ValidationService) -> None:
    result = validator.evaluate(ContractData(), candidate("employee.cuil", "20301234563"))
    assert result.outcome is Outcome.ACCEPTED
    assert result.flag.is_valid and not result.flag.conflict_detected


def test_low_confidence_becomes_conflict(validator: ValidationService) -> None:
    result = validator.evaluate(ContractData(), candidate("employee.dni", "30123456", 0.5))
    assert result.outcome is Outcome.CONFLICT
    assert result.flag.conflict_detected
    assert "umbral" in (result.flag.conflict_detail or "")
    assert result.flag.value_extracted == "30123456"


def test_different_value_is_conflict(validator: ValidationService) -> None:
    contract = ContractData(collected_values={"employee.nombre": "Juan"})
    result = validator.evaluate(contract, candidate("employee.nombre", "Pedro"))
    assert result.outcome is Outcome.CONFLICT
    assert "Juan" in (result.reason or "") and "Pedro" in (result.reason or "")


@pytest.mark.parametrize(
    ("path", "stored", "new"),
    [
        ("employee.nombre", "Juan", "  juan "),
        ("employee.cuil", VALID_CUIL, VALID_CUIL.replace("-", "")),
        ("employee.fecha_nacimiento", "1995-03-15", date(1995, 3, 15)),
        ("terms.remuneracion_bruta", "2500000.00", Decimal("2500000")),
        ("terms.modalidad", "INDETERMINATE", EmploymentType.INDETERMINATE),
    ],
)
def test_equivalent_value_is_unchanged_not_conflict(
    validator: ValidationService, path: str, stored: object, new: object
) -> None:
    contract = ContractData(collected_values={path: stored})
    result = validator.evaluate(contract, candidate(path, new, 0.3))
    assert result.outcome is Outcome.ACCEPTED and result.unchanged


def test_cross_field_check_is_deferred_to_assembly(
    validator: ValidationService, contract: ContractData
) -> None:
    values = {
        "employee.nombre": "Juan",
        "employee.apellido": "Pérez",
        "employee.dni": "30123456",
        "employee.cuil": VALID_CUIL,
        "employee.domicilio": "X 1",
        "employee.fecha_nacimiento": "1995-03-15",
    }
    # Un DNI válido por sí solo no es rechazado aunque no cuadre con el CUIL guardado...
    result = validator.evaluate(
        ContractData(collected_values=values), candidate("employee.dni", "30123457")
    )
    assert result.outcome is Outcome.CONFLICT  # ...solo es un cambio de valor a confirmar.

    # ...y el cruce lo detecta el ensamblado.
    assembled = validator.assemble({**values, "employee.dni": "30123457"})
    assert assembled.sections["employee"] is None
    assert "no coincide" in assembled.errors["employee"]


def test_assemble_builds_only_complete_sections(validator: ValidationService) -> None:
    partial = validator.assemble({"employee.nombre": "Juan"})
    assert all(section is None for section in partial.sections.values())
    assert not partial.errors
