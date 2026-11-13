"""Descarga de documentos: borrador (PDF con marca) y final (PDF o DOCX)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.api import access
from app.api.deps import LocksDep, ServicesDep, UserDep
from app.api.schemas import VerificationOut

router = APIRouter(prefix="/contracts", tags=["documentos"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get(
    "/{contract_id}/document",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}, MEDIA_TYPES["docx"]: {}}}},
)
def download_document(
    contract_id: UUID,
    user: UserDep,
    services: ServicesDep,
    locks: LocksDep,
    version: Literal["draft", "final"] = "final",
    format: Literal["pdf", "docx"] = "pdf",
) -> FileResponse:
    """Descarga el documento.

    - ``version=draft``: PDF preliminar con marca de BORRADOR (solo antes de la decisión).
    - ``version=final``: PDF o DOCX del contrato aprobado; se emite una sola vez y las
      descargas siguientes entregan el mismo archivo.

    El encabezado ``X-Verification-Code`` trae el código impreso en el pie del PDF.
    """
    access.load_visible(services, user, contract_id)

    with locks.hold(contract_id):
        if version == "draft":
            if format != "pdf":
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "El borrador solo se entrega en PDF"
                )
            document = services.exporter.export_draft(contract_id, user.name)
            path, filename = document.pdf_path, f"borrador-{contract_id}.pdf"
            cache = "no-store"
        else:
            document = services.exporter.export_final(contract_id, user.name)
            chosen = document.pdf_path if format == "pdf" else document.docx_path
            assert chosen is not None
            path, filename = chosen, f"contrato-{contract_id}.{format}"
            cache = "private, max-age=0, must-revalidate"

    return FileResponse(
        path,
        media_type=MEDIA_TYPES[format],
        filename=filename,
        headers={"X-Verification-Code": document.verification_code, "Cache-Control": cache},
    )


@router.get("/{contract_id}/verification", response_model=VerificationOut)
def verify_final_document(
    contract_id: UUID, user: UserDep, services: ServicesDep
) -> VerificationOut:
    """Comprueba que el documento final emitido no fue alterado desde su emisión."""
    access.load_visible(services, user, contract_id)
    report = services.exporter.verify_final(contract_id)
    return VerificationOut(
        ok=report.ok, problems=report.problems, verification_code=report.verification_code
    )
