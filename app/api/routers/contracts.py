"""Ciclo de vida del contrato: crear, conversar, confirmar datos y enviar a revisión."""

from __future__ import annotations

from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.api import access, events
from app.api.deps import LocksDep, MessageUserDep, RequesterDep, ServicesDep, UserDep
from app.api.presenters import contract_out, message_out
from app.api.schemas import AuditEntryOut, ConflictResolutionIn, ContractOut, MessageOut
from app.repositories.chat import ChatPage, DocumentRef
from app.schemas.contract import ContractStatus
from app.security.text import normalize_input
from app.services.attachment_store import Upload
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
    user: MessageUserDep,
    services: ServicesDep,
    locks: LocksDep,
    message: Annotated[str, Form(max_length=20000)] = "",
    files: Annotated[Optional[List[UploadFile]], File()] = None,
) -> MessageOut:
    """Un turno de conversación: texto y/o archivos (PDF, PNG, JPG, WEBP).

    El mensaje y la respuesta quedan guardados en el historial (``GET .../messages``) y los
    archivos se conservan para poder verlos de nuevo (``GET .../attachments/{id}``).
    """
    access.load_owned(services, user, contract_id)
    settings = services.settings
    text = normalize_input(message)
    uploads = files or []
    if not text and not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enviá un mensaje o un archivo")
    if len(text) > settings.max_message_chars:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"El mensaje supera el máximo de {settings.max_message_chars} caracteres",
        )
    if len(uploads) > settings.max_upload_files:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Máximo {settings.max_upload_files} archivos por mensaje",
        )

    documents: List[LoadedDocument] = []
    stored_uploads: List[Upload] = []
    for upload in uploads:
        data = upload.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "Un archivo supera el máximo de "
                f"{settings.max_upload_bytes // (1024 * 1024)} MB",
            )
        name = upload.filename or "archivo"
        documents.append(services.loader.load(data, name))
        stored_uploads.append(Upload(name, data))

    with locks.hold(contract_id):
        reply = services.agent.handle_message(contract_id, text, user.name, documents)
        contract = services.contracts.get(contract_id)
        links = (
            [
                DocumentRef(
                    kind="draft",
                    format="pdf",
                    url=f"/contracts/{contract_id}/document?version=draft&format=pdf",
                )
            ]
            if reply.artifacts
            else []
        )
        user_message, agent_message = services.chat.record_exchange(
            contract_id,
            user.name,
            text,
            stored_uploads,
            reply.text,
            reply.intent.value,
            reply.classification_source,
            reply.sources,
            links,
        )
    return message_out(reply, contract, user, user_message, agent_message)


@router.get("/{contract_id}/messages", response_model=ChatPage)
def get_messages(
    contract_id: UUID,
    user: RequesterDep,
    services: ServicesDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[Optional[int], Query(ge=1, description="Traer los anteriores a este seq")] = None,
) -> ChatPage:
    """Historial del chat en orden cronológico, paginado hacia atrás.

    Pedí sin ``before`` para los últimos ``limit`` mensajes; si ``has_more`` es true, volvé a
    pedir con ``before=next_before`` para los anteriores. Solo lo ve el solicitante dueño.
    """
    access.load_owned(services, user, contract_id)
    return services.chat.history(contract_id, limit, before)


@router.get("/{contract_id}/attachments/{attachment_id}", response_class=FileResponse)
def get_attachment(
    contract_id: UUID, attachment_id: UUID, user: RequesterDep, services: ServicesDep
) -> FileResponse:
    """Archivo que el solicitante adjuntó a un mensaje (se muestra en línea)."""
    access.load_owned(services, user, contract_id)
    meta, path = services.chat.attachment_file(contract_id, attachment_id)
    return FileResponse(
        path,
        media_type=meta.media_type,
        filename=meta.filename,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.post("/{contract_id}/conflicts/resolve", response_model=ContractOut)
def resolve_conflict(
    contract_id: UUID,
    body: ConflictResolutionIn,
    user: RequesterDep,
    services: ServicesDep,
    locks: LocksDep,
) -> ContractOut:
    """Confirma o descarta un dato pendiente (equivale a responder «sí»/«no» en el chat)."""
    before = access.load_owned(services, user, contract_id)
    with locks.hold(contract_id):
        contract = services.contracts.resolve_conflict(
            contract_id, body.field_name, body.accept_new, user.name
        )
        services.chat.record_event(
            contract_id,
            user.name,
            events.conflict_resolved(before, body.field_name, body.accept_new),
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
        services.chat.record_event(contract_id, user.name, events.submitted())
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
