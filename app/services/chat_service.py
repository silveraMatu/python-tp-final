"""Historial de conversación de un contrato (mensajes, eventos y adjuntos)."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from app.core.exceptions import ContractNotFoundError
from app.repositories.chat import (
    AttachmentMeta,
    ChatMessage,
    ChatPage,
    ChatRepository,
    ChatRole,
    DocumentRef,
    NewAttachment,
    NewMessage,
)
from app.services.attachment_store import AttachmentStore, Upload

ASSISTANT_NAME = "assistant"
MAX_PAGE_SIZE = 200


class ChatService:
    """Registra y consulta la conversación; no decide nada sobre el contrato."""

    def __init__(self, repository: ChatRepository, store: AttachmentStore) -> None:
        self._repo = repository
        self._store = store

    def record_exchange(
        self,
        contract_id: UUID,
        actor: str,
        user_text: str,
        uploads: Sequence[Upload],
        reply_text: str,
        intent: Optional[str],
        classification_source: Optional[str],
        sources: Sequence[str] = (),
        documents: Sequence[DocumentRef] = (),
    ) -> Tuple[ChatMessage, ChatMessage]:
        """Guarda el mensaje del usuario (con sus adjuntos) y la respuesta, juntos.

        Si algo falla, los archivos ya escritos se borran: no quedan adjuntos huérfanos.
        """
        saved: List[NewAttachment] = []
        try:
            for upload in uploads:
                saved.append(self._store.save(contract_id, upload))
            user, agent = self._repo.append(
                contract_id,
                [
                    NewMessage(ChatRole.USER, actor, user_text, attachments=tuple(saved)),
                    NewMessage(
                        ChatRole.AGENT,
                        ASSISTANT_NAME,
                        reply_text,
                        intent=intent,
                        classification_source=classification_source,
                        sources=sources,
                        documents=documents,
                    ),
                ],
            )
        except BaseException:
            for item in saved:
                self._store.delete(contract_id, item.stored_name)
            raise
        return user, agent

    def record_event(self, contract_id: UUID, actor: str, text: str) -> ChatMessage:
        """Mensaje de sistema (confirmaciones, envío a revisión, decisiones del revisor)."""
        return self._repo.append(contract_id, [NewMessage(ChatRole.SYSTEM, actor, text)])[0]

    def history(self, contract_id: UUID, limit: int = 50, before: Optional[int] = None) -> ChatPage:
        """Página del historial en orden cronológico."""
        return self._repo.page(contract_id, max(1, min(limit, MAX_PAGE_SIZE)), before)

    def attachment_file(self, contract_id: UUID, attachment_id: UUID) -> Tuple[AttachmentMeta, Path]:
        """Metadatos y ruta de un adjunto.

        Raises:
            ContractNotFoundError: no existe (o no pertenece a ese contrato).
        """
        stored = self._repo.get_attachment(contract_id, attachment_id)
        if stored is None:
            raise ContractNotFoundError(str(attachment_id))
        path = self._store.path_of(contract_id, stored.stored_name)
        if not path.is_file():
            raise ContractNotFoundError(str(attachment_id))
        return stored.meta, path
