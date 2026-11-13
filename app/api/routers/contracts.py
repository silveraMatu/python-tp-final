"""Ciclo de vida del contrato: crear, conversar, confirmar datos y enviar a revisión."""

from __future__ import annotations

from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from app.api import access
from app.api.deps import LocksDep, RequesterDep, ServicesDep, UserDep
from app.api.presenters import contract_out, message_out
from app.api.schemas import AuditEntryOut, ConflictResolutionIn, ContractOut, MessageOut
from app.schemas.contract import ContractStatus
from app.services.document_loader import LoadedDocument

router = APIRouter(prefix="/contracts", tags=["contratos"])


@router.post("", response_model=ContractOut, status_code=status.HTTP_201_CREATED)
def create_contract(
    response: Response, user: RequesterDep, services: ServicesDep
) -> ContractOut:
    """Crea un borrador vacío a nombre del solicitante."""
    contract = services.agent.start(user.name)
    response.headers["Location"] = f"/contracts/{contract.id}"
    return contract_out(contract, user)


@router.get("", response_model=List[ContractOut])
def list_contracts(
    user: UserDep, services: ServicesDep, status_filter: Optional[ContractStatus] = None
) -> List[ContractOut]:
    """Contratos visibles para el usuario (más nuevos primero).

    El solicitante ve los suyos; el revisor, los que están en revisión o ya decididos.
    """
    visible = [c for c in services.contracts.list(status_filter) if access.can_view(user, c)]
    return [contract_out(c, user) for c in reversed(visible)]


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(contract_id: UUID, user: UserDep, services: ServicesDep) -> ContractOut:
    """Estado actual del contrato, sus datos y las acciones disponibles."""
    return contract_out(access.load_visible(services, user, contract_id), user)


@router.post("/{contract_id}/messages", response_model=MessageOut)
def send_message(
    contract_id: UUID,
    user: RequesterDep,
    services: ServicesDep,
    locks: LocksDep,
    message: Annotated[str, Form(max_length=4000)] = "",
    files: Annotated[Optional[List[UploadFile]], File()] = None,
) -> MessageOut:
    """Un turno de conversación: texto y/o archivos (PDF, PNG, JPG, WEBP).

    Los archivos se leen en memoria (con tope de tamaño y cantidad) y no se guardan.
    """
    access.load_owned(services, user, contract_id)
    uploads = files or []
    if not message.strip() and not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enviá un mensaje o un archivo")
    settings = services.settings
    if len(uploads) > settings.max_upload_files:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Máximo {settings.max_upload_files} archivos por mensaje",
        )

    documents: List[LoadedDocument] = []
    for upload in uploads:
        data = upload.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"'{upload.filename}' supera el máximo de "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB",
            )
        documents.append(services.loader.load(data, upload.filename or "archivo"))

    with locks.hold(contract_id):
        reply = services.agent.handle_message(contract_id, message, user.name, documents)
        contract = services.contracts.get(contract_id)
    return message_out(reply, contract, user)


@router.post("/{contract_id}/conflicts/resolve", response_model=ContractOut)
def resolve_conflict(
    contract_id: UUID,
    body: ConflictResolutionIn,
    user: RequesterDep,
    services: ServicesDep,
    locks: LocksDep,
) -> ContractOut:
    """Confirma o descarta un dato pendiente (equivale a responder «sí»/«no» en el chat)."""
    access.load_owned(services, user, contract_id)
    with locks.hold(contract_id):
        contract = services.contracts.resolve_conflict(
            contract_id, body.field_name, body.accept_new, user.name
        )
    return contract_out(contract, user)


@router.post("/{contract_id}/submit", response_model=ContractOut)
def submit_for_review(
    contract_id: UUID, user: RequesterDep, services: ServicesDep, locks: LocksDep
) -> ContractOut:
    """Envía el borrador a revisión humana (requiere datos completos y sin conflictos)."""
    access.load_owned(services, user, contract_id)
    with locks.hold(contract_id):
        contract = services.contracts.submit_for_review(contract_id, user.name)
    return contract_out(contract, user)


@router.get("/{contract_id}/history", response_model=List[AuditEntryOut])
def get_history(contract_id: UUID, user: UserDep, services: ServicesDep) -> List[AuditEntryOut]:
    """Auditoría del contrato en orden cronológico."""
    access.load_visible(services, user, contract_id)
    return [
        AuditEntryOut(
            timestamp=e.timestamp,
            actor=e.actor,
            action=e.action,
            status=e.status,
            detail=e.detail,
        )
        for e in services.contracts.history(contract_id)
    ]
