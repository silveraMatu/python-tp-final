from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID

import pymupdf
import pytest
from docx import Document

from app.core.exceptions import (
    ContractRenderError,
    ExportIntegrityError,
    IncompleteContractDataError,
    InvalidStateTransitionError,
    PdfConversionError,
)
from app.repositories.sqlite import SqliteContractRepository
from app.schemas.contract import ContractStatus
from app.services.contract_service import ContractService
from app.services.export_service import (
    DRAFT_FILENAME,
    FINAL_DOCX_FILENAME,
    FINAL_PDF_FILENAME,
    ExportService,
    sha256_of,
)
from app.services.pdf_tools import extract_full_text, find_verification_code
from app.services.template_service import ContractTemplateService
from app.services.validation_service import ValidationService
from tests.helpers import FakePdfConverter
from tests.test_contract_service import FULL_VALUES, batch

TEMPLATE = "app/templates/contrato_trabajo_indeterminado.docx"


@dataclass
class Env:
    exporter: ExportService
    contracts: ContractService
    converter: FakePdfConverter
    contract_id: UUID
    out: Path

    @property
    def folder(self) -> Path:
        return self.out / str(self.contract_id)

    def approve(self) -> None:
        self.contracts.submit_for_review(self.contract_id, "rrhh")
        self.contracts.review(self.contract_id, True, "gerente")


def make_env(tmp_path: Path, converter: Optional[FakePdfConverter] = None, complete: bool = True) -> Env:
    templates = ContractTemplateService(today=lambda: date(2026, 11, 3))
    contracts = ContractService(
        SqliteContractRepository(tmp_path / "db.sqlite"), ValidationService(0.8), templates, TEMPLATE
    )
    converter = converter or FakePdfConverter()
    exporter = ExportService(contracts, templates, converter, TEMPLATE, tmp_path / "out")
    contract = contracts.start("rrhh")
    if complete:
        contracts.apply_extraction(contract.id, batch(FULL_VALUES), "rrhh")
    return Env(exporter, contracts, converter, contract.id, tmp_path / "out")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return make_env(tmp_path)


def actions(env: Env) -> list[str]:
    return [e.action for e in env.contracts.history(env.contract_id)]


# --------------------------------------------------------------------------- #
# Borrador
# --------------------------------------------------------------------------- #


def test_draft_is_a_watermarked_pdf_with_header_and_code(env: Env) -> None:
    result = env.exporter.export_draft(env.contract_id, "rrhh")

    assert result.kind == "draft" and result.docx_path is None and not result.reused
    assert result.pdf_path == env.folder / DRAFT_FILENAME and result.pdf_path.is_file()
    assert not (env.folder / FINAL_DOCX_FILENAME).exists()

    text = extract_full_text(result.pdf_path)
    assert "BORRADOR – pendiente de aprobación humana" in text
    with pymupdf.open(str(result.pdf_path)) as document:
        assert all("BORRADOR" in page.get_text() for page in document)
        assert document.metadata["keywords"].startswith("estado=BORRADOR")
        assert document.metadata["subject"] == f"Contrato {env.contract_id}"
    assert find_verification_code(result.pdf_path) == result.verification_code
    assert result.pdf_sha256 == sha256_of(result.pdf_path)

    assert actions(env)[-1] == "exported_draft"
    assert env.contracts.get(env.contract_id).status is ContractStatus.COLLECTING_DATA


def test_draft_is_overwritten_on_each_request(env: Env) -> None:
    first = env.exporter.export_draft(env.contract_id, "rrhh")
    second = env.exporter.export_draft(env.contract_id, "rrhh")
    assert first.pdf_path == second.pdf_path and env.converter.calls == 2
    assert [p.name for p in env.folder.iterdir()] == [DRAFT_FILENAME]


def test_draft_requires_complete_data(tmp_path: Path) -> None:
    env = make_env(tmp_path, complete=False)
    with pytest.raises(IncompleteContractDataError):
        env.exporter.export_draft(env.contract_id, "rrhh")
    assert env.converter.calls == 0


def test_draft_is_not_available_after_a_decision(env: Env) -> None:
    env.approve()
    with pytest.raises(InvalidStateTransitionError, match="antes de la decisión"):
        env.exporter.export_draft(env.contract_id, "rrhh")


def test_draft_is_available_while_pending_review(env: Env) -> None:
    env.contracts.submit_for_review(env.contract_id, "rrhh")
    assert env.exporter.export_draft(env.contract_id, "rrhh").pdf_path.is_file()


# --------------------------------------------------------------------------- #
# Final
# --------------------------------------------------------------------------- #


def test_final_requires_approval(env: Env) -> None:
    with pytest.raises(InvalidStateTransitionError, match="aprobado"):
        env.exporter.export_final(env.contract_id, "gerente")
    env.contracts.submit_for_review(env.contract_id, "rrhh")
    with pytest.raises(InvalidStateTransitionError):
        env.exporter.export_final(env.contract_id, "gerente")
    assert not env.folder.exists() or not list(env.folder.iterdir())


def test_final_has_pdf_and_docx_without_draft_marks(env: Env) -> None:
    env.exporter.export_draft(env.contract_id, "rrhh")
    env.approve()
    result = env.exporter.export_final(env.contract_id, "gerente")

    assert result.kind == "final" and not result.reused
    assert result.pdf_path.name == FINAL_PDF_FILENAME
    assert result.docx_path is not None and result.docx_path.name == FINAL_DOCX_FILENAME

    pdf_text = extract_full_text(result.pdf_path)
    assert "BORRADOR" not in pdf_text and "ficticio" not in pdf_text.lower()
    assert f"Código de verificación: {result.verification_code}" in " ".join(pdf_text.split())
    with pymupdf.open(str(result.pdf_path)) as document:
        assert document.metadata["keywords"].startswith("estado=FINAL")

    docx = Document(str(result.docx_path))
    assert " ".join(p.text for p in docx.sections[0].header.paragraphs).strip() == ""
    assert "ficticio" not in " ".join(p.text for p in docx.sections[0].footer.paragraphs).lower()


def test_final_review_control_is_filled_from_the_audit(env: Env) -> None:
    env.approve()
    result = env.exporter.export_final(env.contract_id, "gerente")
    assert result.docx_path is not None
    table_text = " | ".join(
        cell.text for table in Document(str(result.docx_path)).tables for row in table.rows for cell in row.cells
    )
    assert "☒ Sí" in table_text and "☒ Aprobado" in table_text
    assert re.search(r"Nombre: gerente Fecha: \d{2}/\d{2}/\d{4}", table_text)
    assert "____" not in table_text.split("CONTROL")[-1]


def test_final_is_recorded_and_issued_only_once(env: Env) -> None:
    env.approve()
    first = env.exporter.export_final(env.contract_id, "gerente")
    calls = env.converter.calls
    second = env.exporter.export_final(env.contract_id, "otro-usuario")

    assert second.reused and env.converter.calls == calls
    assert (second.pdf_sha256, second.docx_sha256, second.verification_code) == (
        first.pdf_sha256,
        first.docx_sha256,
        first.verification_code,
    )
    assert actions(env).count("exported_final") == 1
    record = json.loads(next(e.detail for e in env.contracts.history(env.contract_id) if e.action == "exported_final") or "")
    assert record == {"pdf": first.pdf_sha256, "docx": first.docx_sha256, "code": first.verification_code}


def test_final_rejects_a_missing_approval_record(env: Env) -> None:
    contract = env.contracts.get(env.contract_id)
    contract.status = ContractStatus.APPROVED  # aprobado "a mano", sin pasar por el servicio
    env.contracts._repo.save(contract, "intruso", "forzado")
    with pytest.raises(ExportIntegrityError, match="registro de la aprobación"):
        env.exporter.export_final(env.contract_id, "gerente")


def test_concurrent_final_requests_generate_one_document(env: Env) -> None:
    env.approve()
    results: list[bool] = []

    def worker() -> None:
        results.append(env.exporter.export_final(env.contract_id, "gerente").reused)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True, True, True]
    assert actions(env).count("exported_final") == 1


# --------------------------------------------------------------------------- #
# Integridad
# --------------------------------------------------------------------------- #


def test_verify_final_ok_then_detects_tampering(env: Env) -> None:
    env.approve()
    issued = env.exporter.export_final(env.contract_id, "gerente")
    report = env.exporter.verify_final(env.contract_id)
    assert report.ok and report.problems == [] and report.verification_code == issued.verification_code

    with issued.pdf_path.open("ab") as handle:
        handle.write(b"\n%manipulado")
    tampered = env.exporter.verify_final(env.contract_id)
    assert not tampered.ok and any("PDF fue modificado" in p for p in tampered.problems)
    with pytest.raises(ExportIntegrityError, match="PDF fue modificado"):
        env.exporter.export_final(env.contract_id, "gerente")

    assert issued.docx_path is not None
    issued.docx_path.unlink()
    assert any("falta el archivo DOCX" in p for p in env.exporter.verify_final(env.contract_id).problems)


def test_verify_final_without_a_record(env: Env) -> None:
    report = env.exporter.verify_final(env.contract_id)
    assert not report.ok and "no hay un documento final registrado" in report.problems[0]


def test_verify_final_detects_changed_clauses_with_matching_hash(env: Env) -> None:
    env.approve()
    issued = env.exporter.export_final(env.contract_id, "gerente")
    # Reemplazo el PDF por otro con cláusulas alteradas y actualizo el hash "registrado".
    forged = FakePdfConverter(tamper=lambda t: t.replace("confidencialidad", "publicidad"))
    docx = Document(str(issued.docx_path))
    temp = issued.pdf_path.parent / "tmp"
    temp.mkdir()
    docx.save(str(temp / "x.docx"))
    forged_pdf = forged.convert(temp / "x.docx", temp)
    issued.pdf_path.write_bytes(forged_pdf.read_bytes())
    env.contracts.record_event(
        env.contract_id,
        "intruso",
        "exported_final",
        json.dumps({"pdf": sha256_of(issued.pdf_path), "docx": issued.docx_sha256, "code": issued.verification_code}),
    )
    report = env.exporter.verify_final(env.contract_id)
    assert not report.ok and any("SEXTA" in p for p in report.problems)


# --------------------------------------------------------------------------- #
# Verificaciones durante la generación
# --------------------------------------------------------------------------- #


def test_altered_clauses_in_the_pdf_block_publication(tmp_path: Path) -> None:
    env = make_env(tmp_path, FakePdfConverter(tamper=lambda t: t.replace("EL EMPLEADO", "LA EMPRESA")))
    with pytest.raises(ContractRenderError, match="altera las cláusulas"):
        env.exporter.export_draft(env.contract_id, "rrhh")
    assert not (env.folder / DRAFT_FILENAME).exists()
    assert "exported_draft" not in actions(env)


def test_wrong_verification_code_blocks_publication(tmp_path: Path) -> None:
    env = make_env(tmp_path, FakePdfConverter(wrong_code="AAAA-BBBB-CCCC"))
    with pytest.raises(ContractRenderError, match="código de verificación"):
        env.exporter.export_draft(env.contract_id, "rrhh")
    assert not (env.folder / DRAFT_FILENAME).exists()


def test_conversion_failure_leaves_no_files_and_allows_retry(tmp_path: Path) -> None:
    env = make_env(tmp_path, FakePdfConverter(fail=True))
    env.approve()
    with pytest.raises(PdfConversionError):
        env.exporter.export_final(env.contract_id, "gerente")
    assert list(env.folder.iterdir()) == [] and "exported_final" not in actions(env)

    env.converter.fail = False
    assert env.exporter.export_final(env.contract_id, "gerente").pdf_path.is_file()


def test_verification_code_depends_on_content(tmp_path: Path) -> None:
    first = make_env(tmp_path / "a")
    second = make_env(tmp_path / "b")
    same = first.exporter.export_draft(first.contract_id, "x").verification_code
    assert second.exporter.export_draft(second.contract_id, "x").verification_code == same

    third = make_env(tmp_path / "c", complete=False)
    changed = dict(FULL_VALUES, **{"terms.puesto_funcion": "Analista de Datos"})
    third.contracts.apply_extraction(third.contract_id, batch(changed), "rrhh")
    assert third.exporter.export_draft(third.contract_id, "x").verification_code != same
