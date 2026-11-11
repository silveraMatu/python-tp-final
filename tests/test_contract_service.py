from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core.exceptions import (
    ConflictNotFoundError,
    IncompleteContractDataError,
    InvalidStateTransitionError,
)
from app.repositories.sqlite import SqliteContractRepository
from app.schemas.contract import ContractStatus
from app.schemas.extraction import FieldCandidate
from app.services.contract_service import ContractService
from app.services.template_service import ContractTemplateService
from app.services.validation_service import FIELD_PATHS, ValidationService
from tests.conftest import VALID_CUIL, VALID_CUIT

FULL_VALUES: dict[str, Any] = {
    "employee.nombre": "Juan",
    "employee.apellido": "Pérez",
    "employee.dni": "30123456",
    "employee.cuil": VALID_CUIL,
    "employee.domicilio": "Calle Falsa 742, Córdoba",
    "employee.fecha_nacimiento": "1995-03-15",
    "company.razon_social": "HumanIA S.A.",
    "company.cuit": VALID_CUIT,
    "company.domicilio_legal": "Av. Ejemplo 1234, Córdoba",
    "company.apoderado_nombre": "María Gómez",
    "company.apoderado_cargo": "Gerente de RR. HH.",
    "terms.puesto_funcion": "Desarrollador de Software",
    "terms.fecha_inicio": "2026-11-09",
    "terms.modalidad": "INDETERMINATE",
    "terms.remuneracion_bruta": "2500000",
    "terms.jornada_laboral": "de lunes a viernes, de 9:00 a 17:00 hs",
    "terms.lugar_trabajo": "las oficinas de HumanIA S.A., Córdoba",
}


def batch(values: dict[str, Any], confidence: float = 0.95) -> list[FieldCandidate]:
    return [
        FieldCandidate(field_name=path, value=value, confidence_score=confidence)
        for path, value in values.items()
    ]


@pytest.fixture
def service(tmp_path: Path) -> ContractService:
    templates = ContractTemplateService(today=lambda: date(2026, 11, 3))
    template_path = tmp_path / "plantilla.docx"
    templates.init_base_template(str(template_path))
    return ContractService(
        SqliteContractRepository(tmp_path / "contracts.db"),
        ValidationService(confidence_threshold=0.8),
        templates,
        template_path,
    )


def test_full_flow_to_approval_and_final_render(service: ContractService, tmp_path: Path) -> None:
    created = service.start("rrhh")
    assert created.status is ContractStatus.INITIAL

    first = service.apply_extraction(
        created.id, batch({k: v for k, v in FULL_VALUES.items() if k.startswith("employee")}), "rrhh"
    )
    assert first.contract.status is ContractStatus.COLLECTING_DATA
    assert first.contract.employee is not None and first.contract.employee.cuil == VALID_CUIL
    assert first.missing_fields[0].startswith("company.")
    assert not first.contract.is_complete

    rest = {k: v for k, v in FULL_VALUES.items() if not k.startswith("employee")}
    done = service.apply_extraction(created.id, batch(rest), "rrhh").contract
    assert done.is_complete and done.missing_fields == []

    with pytest.raises(InvalidStateTransitionError):
        service.render(created.id, str(tmp_path / "final.docx"), "rrhh", require_approved=True)
    draft = service.render(created.id, str(tmp_path / "draft.docx"), "rrhh")
    assert Path(draft).is_file()

    service.submit_for_review(created.id, "rrhh")
    service.review(created.id, approved=True, actor="gerente")
    final = service.render(created.id, str(tmp_path / "final.docx"), "gerente", require_approved=True)
    assert Path(final).is_file()

    assert service.get(created.id).status is ContractStatus.APPROVED
    assert [(h.actor, h.action) for h in service.history(created.id)] == [
        ("rrhh", "created"),
        ("rrhh", "extraction_applied"),
        ("rrhh", "extraction_applied"),
        ("rrhh", "rendered_draft"),
        ("rrhh", "submitted_for_review"),
        ("gerente", "approved"),
        ("gerente", "rendered_final"),
    ]
    with pytest.raises(InvalidStateTransitionError):
        service.apply_extraction(created.id, batch({"employee.nombre": "Otro"}), "rrhh")


def test_invalid_and_unknown_fields_are_rejected_not_applied(service: ContractService) -> None:
    contract = service.start("rrhh")
    result = service.apply_extraction(
        contract.id,
        batch({"employee.dni": "12ab", "employee.salario": "1", "employee.nombre": "Juan"}),
        "rrhh",
    )
    assert result.accepted == ["employee.nombre"]
    assert set(result.rejected) == {"employee.dni", "employee.salario"}
    assert "employee.dni" not in result.contract.collected_values
    assert result.contract.status is ContractStatus.COLLECTING_DATA
    assert "employee.dni" in result.missing_fields


def test_rejection_does_not_overwrite_accepted_value(service: ContractService) -> None:
    contract = service.start("rrhh")
    service.apply_extraction(contract.id, batch({"employee.dni": "30123456"}), "rrhh")
    result = service.apply_extraction(contract.id, batch({"employee.dni": "xx"}), "rrhh")
    assert result.contract.collected_values["employee.dni"] == "30123456"
    flag = next(f for f in result.contract.validation_flags if f.field_name == "employee.dni")
    assert flag.is_valid


def test_low_confidence_conflict_and_resolution(service: ContractService) -> None:
    contract = service.start("rrhh")
    result = service.apply_extraction(
        contract.id, batch({"employee.dni": "30123456"}, confidence=0.4), "ocr"
    )
    assert result.conflicts == ["employee.dni"]
    assert result.contract.status is ContractStatus.CONFLICT_DETECTED
    assert "employee.dni" not in result.contract.collected_values

    with pytest.raises(InvalidStateTransitionError):
        service.submit_for_review(contract.id, "rrhh")

    resolved = service.resolve_conflict(contract.id, "employee.dni", accept_new=True, actor="rrhh")
    assert resolved.collected_values["employee.dni"] == "30123456"
    assert resolved.status is ContractStatus.COLLECTING_DATA
    assert not resolved.has_conflicts()

    with pytest.raises(ConflictNotFoundError):
        service.resolve_conflict(contract.id, "employee.dni", accept_new=True, actor="rrhh")


def test_conflict_with_previous_value_can_keep_the_old_one(service: ContractService) -> None:
    contract = service.start("rrhh")
    service.apply_extraction(contract.id, batch({"employee.nombre": "Juan"}), "rrhh")
    result = service.apply_extraction(contract.id, batch({"employee.nombre": "Pedro"}), "ocr")
    assert result.contract.status is ContractStatus.CONFLICT_DETECTED
    assert result.contract.collected_values["employee.nombre"] == "Juan"

    kept = service.resolve_conflict(contract.id, "employee.nombre", accept_new=False, actor="rrhh")
    assert kept.collected_values["employee.nombre"] == "Juan"
    assert kept.status is ContractStatus.COLLECTING_DATA


def test_rejecting_first_low_confidence_value_discards_it(service: ContractService) -> None:
    contract = service.start("rrhh")
    service.apply_extraction(contract.id, batch({"employee.dni": "30123456"}, 0.2), "ocr")
    discarded = service.resolve_conflict(contract.id, "employee.dni", False, "rrhh")
    assert "employee.dni" not in discarded.collected_values
    assert not discarded.validation_flags
    assert discarded.status is ContractStatus.COLLECTING_DATA


def test_cross_field_mismatch_blocks_completion_until_fixed(service: ContractService) -> None:
    contract = service.start("rrhh")
    service.apply_extraction(contract.id, batch(FULL_VALUES), "rrhh")
    service.apply_extraction(contract.id, batch({"employee.dni": "30123457"}), "rrhh")
    broken = service.resolve_conflict(contract.id, "employee.dni", True, "rrhh")

    assert broken.employee is None and not broken.is_complete
    assert any(f.field_name == "employee" and not f.is_valid for f in broken.validation_flags)
    with pytest.raises(InvalidStateTransitionError):
        service.submit_for_review(contract.id, "rrhh")

    # Corregir también el CUIL (DNI 30123457 -> verificador calculado) lo repara.
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    base = "2030123457"
    remainder = sum(int(d) * w for d, w in zip(base, weights)) % 11
    check = 0 if remainder == 0 else 11 - remainder
    service.apply_extraction(contract.id, batch({"employee.cuil": f"20-30123457-{check}"}), "rrhh")
    fixed = service.resolve_conflict(contract.id, "employee.cuil", True, "rrhh")
    assert fixed.employee is not None and fixed.is_complete
    assert not any(f.field_name == "employee" for f in fixed.validation_flags)


def test_review_requires_pending_state(service: ContractService) -> None:
    contract = service.start("rrhh")
    with pytest.raises(InvalidStateTransitionError):
        service.review(contract.id, True, "gerente")


def test_reject_and_request_changes(service: ContractService) -> None:
    contract = service.start("rrhh")
    service.apply_extraction(contract.id, batch(FULL_VALUES), "rrhh")
    service.submit_for_review(contract.id, "rrhh")
    assert service.request_changes(contract.id, "gerente").status is ContractStatus.COLLECTING_DATA
    service.submit_for_review(contract.id, "rrhh")
    assert service.review(contract.id, False, "gerente").status is ContractStatus.REJECTED


def test_render_incomplete_contract(service: ContractService, tmp_path: Path) -> None:
    contract = service.start("rrhh")
    with pytest.raises(IncompleteContractDataError):
        service.render(contract.id, str(tmp_path / "x.docx"), "rrhh")


def test_all_field_paths_are_collectable() -> None:
    assert set(FULL_VALUES) == set(FIELD_PATHS)
