"""Exportación del contrato a PDF/DOCX (F09/F10).

- **Borrador** (cualquier estado previo a la decisión): solo PDF, con marca de agua
  diagonal y encabezado de borrador. Se sobrescribe en cada pedido.
- **Final** (solo ``APPROVED``): PDF + DOCX, sin marca, con el control de revisión
  completado desde la auditoría. Se genera una sola vez; después se sirve el mismo
  archivo, comprobando su hash contra el registrado.

En ambos casos se verifica, sobre el PDF ya convertido, que las cláusulas sean las
autorizadas y que el código de verificación del pie sea el esperado.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict, Dict, Final, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.exceptions import (
    ContractRenderError,
    ExportIntegrityError,
    InvalidStateTransitionError,
)
from app.schemas.contract import ContractData, ContractStatus
from app.services import pdf_tools
from app.services.contract_service import ContractService
from app.services.pdf_converter import PdfConverter, build_pdf_converter
from app.services.template_service import ContractTemplateService, RenderOptions, ReviewRecord

DRAFT_FILENAME: Final[str] = "borrador.pdf"
FINAL_PDF_FILENAME: Final[str] = "contrato_final.pdf"
FINAL_DOCX_FILENAME: Final[str] = "contrato_final.docx"
WATERMARK_TEXT: Final[str] = "BORRADOR"
_DRAFTABLE = frozenset(
    {
        ContractStatus.INITIAL,
        ContractStatus.COLLECTING_DATA,
        ContractStatus.CONFLICT_DETECTED,
        ContractStatus.PENDING_HUMAN_REVIEW,
    }
)


@dataclass(frozen=True)
class ExportedDocument:
    """Documento generado (o reutilizado) con sus huellas."""

    kind: str  # "draft" | "final"
    pdf_path: Path
    pdf_sha256: str
    verification_code: str
    docx_path: Optional[Path] = None
    docx_sha256: Optional[str] = None
    reused: bool = False


@dataclass(frozen=True)
class VerificationReport:
    """Resultado de comprobar un documento final contra lo registrado."""

    ok: bool
    problems: List[str] = field(default_factory=list)
    verification_code: Optional[str] = None


def sha256_of(path: Path) -> str:
    """SHA-256 hexadecimal de un archivo."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class ExportService:
    """Genera, guarda y verifica los documentos de un contrato."""

    def __init__(
        self,
        contracts: ContractService,
        templates: ContractTemplateService,
        converter: PdfConverter,
        template_path: str | Path,
        output_dir: str | Path,
        timezone: str = "America/Argentina/Cordoba",
    ) -> None:
        self._contracts = contracts
        self._templates = templates
        self._converter = converter
        self._template_path = str(template_path)
        self._output_dir = Path(output_dir)
        self._timezone = ZoneInfo(timezone)
        self._locks: DefaultDict[UUID, threading.Lock] = defaultdict(threading.Lock)
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ #
    # Borrador
    # ------------------------------------------------------------------ #

    def export_draft(self, contract_id: UUID, actor: str) -> ExportedDocument:
        """PDF preliminar con marca de BORRADOR.

        Raises:
            InvalidStateTransitionError: el contrato ya fue aprobado o rechazado.
            IncompleteContractDataError: faltan datos o hay errores.
            UnsupportedModalityError: no hay plantilla aprobada para la modalidad.
            ContractRenderError: falló el render, la conversión o la verificación.
        """
        with self._lock_for(contract_id):
            contract = self._contracts.get(contract_id)
            if contract.status not in _DRAFTABLE:
                raise InvalidStateTransitionError(
                    contract.status.value,
                    "BORRADOR",
                    "el borrador solo existe antes de la decisión del revisor",
                )
            options = RenderOptions(draft=True)
            with tempfile.TemporaryDirectory(prefix="export-") as temp:
                temp_dir = Path(temp)
                pdf, code = self._build_pdf(contract, temp_dir, "borrador", options)
                pdf_tools.apply_watermark(pdf, WATERMARK_TEXT)
                self._stamp_metadata(pdf, contract_id, "BORRADOR", code)
                target = self._folder(contract_id) / DRAFT_FILENAME
                self._publish(pdf, target)

            sha = sha256_of(target)
            self._contracts.record_event(
                contract_id, actor, "exported_draft", json.dumps({"pdf": sha, "code": code})
            )
            return ExportedDocument("draft", target, sha, code)

    # ------------------------------------------------------------------ #
    # Final
    # ------------------------------------------------------------------ #

    def export_final(self, contract_id: UUID, actor: str) -> ExportedDocument:
        """PDF + DOCX definitivos de un contrato aprobado (se generan una sola vez).

        Raises:
            InvalidStateTransitionError: el contrato no está aprobado.
            ExportIntegrityError: no hay registro de la aprobación, o un final ya emitido
                fue alterado o falta.
        """
        with self._lock_for(contract_id):
            contract = self._contracts.get(contract_id)
            if contract.status is not ContractStatus.APPROVED:
                raise InvalidStateTransitionError(
                    contract.status.value,
                    ContractStatus.APPROVED.value,
                    "el documento final requiere un contrato aprobado",
                )

            folder = self._folder(contract_id)
            pdf_target, docx_target = folder / FINAL_PDF_FILENAME, folder / FINAL_DOCX_FILENAME

            recorded = self._recorded_final(contract_id)
            if recorded is not None:
                problems = self._file_problems(recorded, pdf_target, docx_target)
                if problems:
                    raise ExportIntegrityError(
                        "El documento final emitido no coincide con lo registrado: "
                        + "; ".join(problems)
                    )
                return ExportedDocument(
                    "final",
                    pdf_target,
                    recorded["pdf"],
                    recorded["code"],
                    docx_target,
                    recorded["docx"],
                    reused=True,
                )

            options = RenderOptions(draft=False, review=self._review_record(contract_id))
            with tempfile.TemporaryDirectory(prefix="export-") as temp:
                temp_dir = Path(temp)
                pdf, code = self._build_pdf(contract, temp_dir, "contrato_final", options)
                self._stamp_metadata(pdf, contract_id, "FINAL", code)
                docx = temp_dir / "contrato_final.docx"
                self._publish(docx, docx_target)
                self._publish(pdf, pdf_target)

            record = {"pdf": sha256_of(pdf_target), "docx": sha256_of(docx_target), "code": code}
            self._contracts.record_event(contract_id, actor, "exported_final", json.dumps(record))
            return ExportedDocument(
                "final",
                pdf_target,
                record["pdf"],
                code,
                docx_target,
                record["docx"],
            )

    def verify_final(self, contract_id: UUID) -> VerificationReport:
        """Comprueba que el final emitido siga igual a lo registrado.

        Revisa existencia, hashes, código de verificación del pie y que las cláusulas
        del PDF sean las autorizadas. No modifica nada.
        """
        contract = self._contracts.get(contract_id)
        recorded = self._recorded_final(contract_id)
        if recorded is None:
            return VerificationReport(False, ["no hay un documento final registrado"])

        folder = self._folder(contract_id)
        pdf_path, docx_path = folder / FINAL_PDF_FILENAME, folder / FINAL_DOCX_FILENAME
        problems = self._file_problems(recorded, pdf_path, docx_path)
        found_code: Optional[str] = None
        if pdf_path.is_file():
            found_code = pdf_tools.find_verification_code(pdf_path)
            if found_code != recorded["code"]:
                problems.append("el código de verificación del PDF no coincide con el registrado")
            try:
                context = self._templates.build_context(contract)
            except Exception as exc:  # contrato ilegible o incompleto
                problems.append(f"no se pudo reconstruir el contenido esperado: {exc}")
            else:
                problems.extend(
                    pdf_tools.clause_violations(
                        pdf_tools.extract_body_text(pdf_path),
                        self._templates.rendered_clauses(context),
                    )
                )
        return VerificationReport(not problems, problems, found_code)

    # ------------------------------------------------------------------ #
    # Piezas internas
    # ------------------------------------------------------------------ #

    def _build_pdf(
        self, contract: ContractData, temp_dir: Path, stem: str, options: RenderOptions
    ) -> tuple[Path, str]:
        """Renderiza el DOCX, lo convierte y verifica el PDF. Devuelve (pdf, código)."""
        docx_path = Path(
            self._templates.render_contract(
                contract, self._template_path, str(temp_dir / f"{stem}.docx"), options
            )
        )
        context = self._templates.build_context(contract, options)
        pdf_path = self._converter.convert(docx_path, temp_dir)

        violations = pdf_tools.clause_violations(
            pdf_tools.extract_body_text(pdf_path), self._templates.rendered_clauses(context)
        )
        if violations:
            raise ContractRenderError(
                "El PDF generado altera las cláusulas legales: " + "; ".join(violations)
            )
        code = str(context["codigo_verificacion"])
        printed = pdf_tools.find_verification_code(pdf_path)
        if printed != code:
            raise ContractRenderError(
                f"El código de verificación del PDF ({printed}) no es el esperado ({code})"
            )
        return pdf_path, code

    @staticmethod
    def _stamp_metadata(pdf: Path, contract_id: UUID, state: str, code: str) -> None:
        pdf_tools.set_metadata(
            pdf,
            title="Contrato de trabajo",
            subject=f"Contrato {contract_id}",
            keywords=f"estado={state}; verificacion={code}",
            author="HumanIA S.A.",
        )

    def _review_record(self, contract_id: UUID) -> ReviewRecord:
        """Quién aprobó y cuándo, según la auditoría."""
        approvals = [e for e in self._contracts.history(contract_id) if e.action == "approved"]
        if not approvals:
            raise ExportIntegrityError(
                "No hay registro de la aprobación en la auditoría; no se emite el documento final"
            )
        entry = approvals[-1]
        when = entry.timestamp.astimezone(self._timezone).date()
        return ReviewRecord(reviewer=entry.actor, reviewed_on=when)

    def _recorded_final(self, contract_id: UUID) -> Optional[Dict[str, str]]:
        """Último registro de ``exported_final`` en la auditoría (hashes y código)."""
        records = [e for e in self._contracts.history(contract_id) if e.action == "exported_final"]
        if not records or not records[-1].detail:
            return None
        try:
            data: Dict[str, Any] = json.loads(records[-1].detail or "")
            return {key: str(data[key]) for key in ("pdf", "docx", "code")}
        except (ValueError, KeyError):
            raise ExportIntegrityError("El registro del documento final en la auditoría es inválido")

    @staticmethod
    def _file_problems(recorded: Dict[str, str], pdf: Path, docx: Path) -> List[str]:
        problems: List[str] = []
        for label, path, expected in (("PDF", pdf, recorded["pdf"]), ("DOCX", docx, recorded["docx"])):
            if not path.is_file():
                problems.append(f"falta el archivo {label}")
            elif sha256_of(path) != expected:
                problems.append(f"el {label} fue modificado (el hash no coincide)")
        return problems

    def _folder(self, contract_id: UUID) -> Path:
        folder = (self._output_dir / str(contract_id)).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _publish(source: Path, target: Path) -> None:
        """Copia ``source`` a ``target`` de forma atómica (puede ser otro filesystem)."""
        handle, temp_name = tempfile.mkstemp(dir=str(target.parent), suffix=target.suffix)
        os.close(handle)
        try:
            shutil.copyfile(source, temp_name)
            os.replace(temp_name, target)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def _lock_for(self, contract_id: UUID) -> threading.Lock:
        with self._locks_guard:
            return self._locks[contract_id]


def build_export_service(
    settings: Settings, contracts: ContractService, templates: ContractTemplateService
) -> ExportService:
    """Construye el servicio de exportación a partir de la configuración."""
    return ExportService(
        contracts=contracts,
        templates=templates,
        converter=build_pdf_converter(settings),
        template_path=settings.template_path,
        output_dir=settings.output_dir,
        timezone=settings.timezone,
    )
