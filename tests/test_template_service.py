from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from docx import Document

from app.core.exceptions import (
    ContractRenderError,
    IncompleteContractDataError,
    TemplateNotFoundError,
    UnsupportedModalityError,
)
from app.schemas.contract import ContractData, EmploymentType, FieldValidation
from app.services.template_service import (
    BLANK_REVIEW,
    DRAFT_HEADER,
    STATIC_CLAUSES,
    ContractTemplateService,
    RenderOptions,
    ReviewRecord,
    amount_in_words,
    format_ars,
    format_dni,
)


@pytest.fixture
def service() -> ContractTemplateService:
    return ContractTemplateService(city="Córdoba", today=lambda: date(2026, 11, 3))


@pytest.fixture
def template_path(service: ContractTemplateService, tmp_path: Path) -> str:
    path = tmp_path / "plantilla.docx"
    service.init_base_template(str(path))
    return str(path)


def _all_text(path: str) -> str:
    document = Document(path)
    chunks = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            chunks.extend(cell.text for cell in row.cells)
    return "\n".join(chunks)


def test_formatters() -> None:
    assert format_dni("30123456") == "30.123.456"
    assert format_dni("5123456") == "5.123.456"
    assert format_ars(Decimal("2500000")) == "$ 2.500.000"
    assert format_ars(Decimal("2500000.5")) == "$ 2.500.000,50"
    assert amount_in_words(Decimal("2500000")) == "dos millones quinientos mil"
    assert amount_in_words(Decimal("31000")) == "treinta y un mil"
    assert amount_in_words(Decimal("1500.25")) == "mil quinientos con 25/100"


def test_template_has_all_authorized_clauses(
    service: ContractTemplateService, template_path: str
) -> None:
    service.verify_template(template_path)
    text = _all_text(template_path)
    for clause in STATIC_CLAUSES:
        assert clause.heading in text
        assert clause.body in text
    assert len(STATIC_CLAUSES) == 8
    assert len({c.sha256 for c in STATIC_CLAUSES}) == 8


def test_render_contract_injects_values(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    result = service.render_contract(contract, template_path, str(tmp_path / "out" / "c.docx"))

    assert Path(result).is_absolute()
    text = _all_text(result)
    assert "{{" not in text and "{%" not in text
    for expected in (
        "En la ciudad de Córdoba, a los 3 días del mes de noviembre de 2026",
        "HumanIA S.A.",
        "CUIT 30-71234567-1",
        "Juan Pérez, DNI 30.123.456",
        "15/03/1995",
        "09/11/2026",
        "$ 2.500.000 (pesos argentinos, dos millones quinientos mil)",
        "en el puesto de Desarrollador de Software,",
        "Contrato por tiempo indeterminado",
    ):
        assert expected in text, expected


def test_render_escapes_special_characters(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    assert contract.company is not None
    contract.company = contract.company.model_copy(update={"razon_social": "Pérez & Hijos <S.R.L.>"})
    result = service.render_contract(contract, template_path, str(tmp_path / "c.docx"))
    assert "Pérez & Hijos <S.R.L.>" in _all_text(result)


def test_incomplete_contract_is_rejected(
    service: ContractTemplateService, template_path: str, tmp_path: Path
) -> None:
    output = tmp_path / "c.docx"
    with pytest.raises(IncompleteContractDataError) as info:
        service.render_contract(ContractData(), template_path, str(output))
    assert "employee.dni" in info.value.missing_fields
    assert not output.exists()


def test_flagged_contract_is_rejected(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    contract.validation_flags.append(
        FieldValidation(field_name="employee.dni", is_valid=False, confidence_score=0.3)
    )
    with pytest.raises(IncompleteContractDataError) as info:
        service.render_contract(contract, template_path, str(tmp_path / "c.docx"))
    assert info.value.invalid_fields == ["employee.dni"]


def test_missing_template(
    service: ContractTemplateService, contract: ContractData, tmp_path: Path
) -> None:
    with pytest.raises(TemplateNotFoundError):
        service.render_contract(contract, str(tmp_path / "nope.docx"), str(tmp_path / "c.docx"))


def test_unsupported_modality(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    assert contract.terms is not None
    contract.terms = contract.terms.model_copy(update={"modalidad": EmploymentType.FIXED_TERM})
    with pytest.raises(UnsupportedModalityError):
        service.render_contract(contract, template_path, str(tmp_path / "c.docx"))


def test_tampered_template_is_rejected(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    document = Document(template_path)
    target = next(p for p in document.paragraphs if p.text == STATIC_CLAUSES[5].body)
    target.runs[0].text = "EL EMPLEADO no tiene deber de confidencialidad."
    tampered = tmp_path / "tampered.docx"
    document.save(str(tampered))

    output = tmp_path / "c.docx"
    with pytest.raises(ContractRenderError, match="SEXTA"):
        service.render_contract(contract, str(tampered), str(output))
    assert not output.exists()


def test_extra_clause_in_template_is_rejected(
    service: ContractTemplateService, template_path: str, tmp_path: Path
) -> None:
    document = Document(template_path)
    document.add_paragraph("NOVENA – Cláusula inventada.")
    tampered = tmp_path / "tampered.docx"
    document.save(str(tampered))
    with pytest.raises(ContractRenderError, match="no autorizada"):
        service.verify_template(str(tampered))


def test_template_with_unknown_variable_fails_and_cleans_up(
    service: ContractTemplateService, contract: ContractData, tmp_path: Path
) -> None:
    path = tmp_path / "base.docx"
    service.init_base_template(str(path))
    document = Document(str(path))
    document.add_paragraph("{{ employee.no_existe }}")
    broken = tmp_path / "broken.docx"
    document.save(str(broken))

    output = tmp_path / "c.docx"
    with pytest.raises(ContractRenderError):
        service.render_contract(contract, str(broken), str(output))
    assert not output.exists()


def _header_footer(path: str) -> tuple[str, str]:
    section = Document(path).sections[0]
    return (
        " ".join(p.text for p in section.header.paragraphs).strip(),
        " ".join(p.text for p in section.footer.paragraphs).strip(),
    )


def test_default_render_has_blank_review_and_no_draft_header(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    result = service.render_contract(contract, template_path, str(tmp_path / "c.docx"))
    text = _all_text(result)
    for value in BLANK_REVIEW.values():
        assert value in text
    header, footer = _header_footer(result)
    assert header == "" and "ficticio" not in footer.lower()
    code = service.build_context(contract)["codigo_verificacion"]
    assert footer.startswith(f"Código de verificación: {code}")


def test_draft_option_adds_the_header_only(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    draft = service.render_contract(
        contract, template_path, str(tmp_path / "d.docx"), RenderOptions(draft=True)
    )
    assert _header_footer(draft)[0] == DRAFT_HEADER
    for clause in service.rendered_clauses(service.build_context(contract)):
        assert clause[1] in _all_text(draft)


def test_review_record_fills_the_control_table(
    service: ContractTemplateService, template_path: str, contract: ContractData, tmp_path: Path
) -> None:
    options = RenderOptions(review=ReviewRecord("gerente", date(2026, 11, 12)))
    result = service.render_contract(contract, template_path, str(tmp_path / "f.docx"), options)
    text = _all_text(result)
    assert "☒ Sí" in text and "☒ Aprobado" in text
    assert "Nombre: gerente Fecha: 12/11/2026" in text
    assert "Ninguna / Detalle" not in text


def test_verification_code_is_stable_and_content_sensitive(
    service: ContractTemplateService, contract: ContractData
) -> None:
    code = service.build_context(contract)["codigo_verificacion"]
    assert re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", code)
    assert service.build_context(contract)["codigo_verificacion"] == code
    assert service.build_context(contract, RenderOptions(draft=True))["codigo_verificacion"] == code

    assert contract.terms is not None
    other = contract.model_copy(deep=True)
    other.terms = contract.terms.model_copy(update={"puesto_funcion": "Analista"})
    assert service.build_context(other)["codigo_verificacion"] != code
    later = ContractTemplateService(today=lambda: date(2026, 12, 1))
    assert later.build_context(contract)["codigo_verificacion"] != code
