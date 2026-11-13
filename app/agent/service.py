"""Fachada del agente: un turno de conversación = un ``handle_message``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from uuid import UUID

from app.agent import replies
from app.agent.graph import AgentState, ContractAgentGraph
from app.agent.intents import Intent, IntentClassifier
from app.schemas.contract import ContractData, ContractStatus
from app.security.injection import ScanResult, scan
from app.security.output_guard import OutputGuard
from app.security.text import normalize_input
from app.services.contract_service import ContractService
from app.services.document_loader import LoadedDocument
from app.services.export_service import ExportService
from app.services.rag_service import RagService
from app.services.extraction_service import ExtractionService

security_log = logging.getLogger("humania.security")


@dataclass(frozen=True)
class PendingConflict:
    """Dato a la espera de confirmación del usuario."""

    field_name: str
    label: str
    value: str
    detail: Optional[str]


@dataclass(frozen=True)
class AgentReply:
    """Respuesta de un turno, con el estado actual del contrato."""

    text: str
    intent: Intent
    status: ContractStatus
    missing_fields: List[str]
    pending_conflicts: List[PendingConflict] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    classification_source: str = ""


class AgentService:
    """Orquesta un turno del agente sobre un contrato existente.

    El estado vive en el repositorio (vía ``ContractService``); cada turno es
    independiente y reconstruye todo lo que necesita desde ahí.
    """

    def __init__(
        self,
        contracts: ContractService,
        extraction: ExtractionService,
        classifier: IntentClassifier,
        rag: Optional[RagService],
        exporter: ExportService,
        output_guard: Optional[OutputGuard] = None,
        max_message_chars: int = 4000,
    ) -> None:
        self._guard = output_guard or OutputGuard()
        self._max_message_chars = max_message_chars
        self._contracts = contracts
        self._graph = ContractAgentGraph(contracts, extraction, classifier, rag, exporter).compile()

    def start(self, actor: str) -> ContractData:
        """Crea un contrato nuevo (estado ``INITIAL``)."""
        return self._contracts.start(actor)

    def handle_message(
        self,
        contract_id: UUID,
        message: str,
        actor: str,
        documents: Sequence[LoadedDocument] = (),
    ) -> AgentReply:
        """Procesa un mensaje (y adjuntos ya cargados) sobre ``contract_id``.

        Raises:
            ContractNotFoundError: el contrato no existe.
            LLMUnavailableError: el modelo no responde (créditos, red).
        """
        clean = normalize_input(message)[: self._max_message_chars]
        verdict = scan(clean)
        if verdict.blocked:
            return self._blocked_reply(contract_id, actor, verdict)

        safe_documents: List[LoadedDocument] = []
        discarded: List[str] = []
        for document in documents:
            found = scan(normalize_input(document.text)) if document.text else ScanResult()
            if found.blocked:
                discarded.append(document.filename)
                self._audit_block(contract_id, actor, found, f"documento:{len(discarded)}")
            else:
                safe_documents.append(document)

        if discarded and not safe_documents and not clean:
            return self._notice_reply(contract_id, discarded)

        state: AgentState = {
            "contract_id": contract_id,
            "actor": actor,
            "message": clean,
            "documents": tuple(safe_documents),
            "parts": [],
            "artifacts": [],
            "sources": [],
        }
        final = self._graph.invoke(state)

        contract = self._contracts.get(contract_id)
        text = final["reply"]
        if discarded:
            notes = "\n".join(replies.DOCUMENT_DISCARDED.format(name=name) for name in discarded)
            text = f"{notes}\n\n{text}"
        text = self._filter_output(text, contract, clean, safe_documents)
        return self._build_reply(
            text,
            final["intent"],
            contract,
            list(final.get("artifacts", [])),
            list(dict.fromkeys(final.get("sources", []))),
            final.get("classification_source", ""),
        )

    # ------------------------------------------------------------------ #

    def _filter_output(
        self,
        text: str,
        contract: ContractData,
        message: str,
        documents: Sequence[LoadedDocument],
    ) -> str:
        """Última barrera: tope de longitud y filtro de fugas sobre cualquier respuesta."""
        known: List[str] = [message, *[str(v) for v in contract.collected_values.values()]]
        known.extend(str(flag.value_extracted) for flag in contract.validation_flags)
        known.extend(doc.text for doc in documents if doc.text)
        guarded = self._guard.check(text, context=known, allowed_ids=[str(contract.id)])
        if guarded.blocked or guarded.redactions or guarded.truncated:
            security_log.warning(
                "salida filtrada contrato=%s motivos=%s", contract.id, ",".join(guarded.reasons)
            )
        return guarded.text

    def _audit_block(
        self, contract_id: UUID, actor: str, found: ScanResult, origin: str
    ) -> None:
        """Deja constancia (sin el contenido) de un intento bloqueado."""
        security_log.warning(
            "entrada bloqueada contrato=%s usuario=%s origen=%s categorias=%s",
            contract_id, actor, origin, found.label(),
        )  # fmt: skip
        self._contracts.record_event(
            contract_id, actor, "security_blocked", f"{origin}:{found.label()}"
        )

    def _blocked_reply(self, contract_id: UUID, actor: str, found: ScanResult) -> AgentReply:
        self._audit_block(contract_id, actor, found, "mensaje")
        contract = self._contracts.get(contract_id)
        return self._build_reply(
            f"{replies.SECURITY_REFUSAL}\n\n{replies.next_step(contract)}",
            Intent.BLOCKED,
            contract,
            [],
            [],
            "security",
        )

    def _notice_reply(self, contract_id: UUID, discarded: Sequence[str]) -> AgentReply:
        contract = self._contracts.get(contract_id)
        notes = "\n".join(replies.DOCUMENT_DISCARDED.format(name=name) for name in discarded)
        return self._build_reply(
            f"{notes}\n\n{replies.next_step(contract)}", Intent.BLOCKED, contract, [], [], "security"
        )

    @staticmethod
    def _build_reply(
        text: str,
        intent: Intent,
        contract: ContractData,
        artifacts: List[str],
        sources: List[str],
        classification_source: str,
    ) -> AgentReply:
        conflicts = [
            PendingConflict(
                field_name=flag.field_name,
                label=replies.label(flag.field_name),
                value=replies.display_value(flag.field_name, flag.value_extracted),
                detail=flag.conflict_detail,
            )
            for flag in replies.pending_conflicts(contract)
        ]
        return AgentReply(
            text=text,
            intent=intent,
            status=contract.status,
            missing_fields=contract.get_missing_fields(),
            pending_conflicts=conflicts,
            artifacts=artifacts,
            sources=sources,
            classification_source=classification_source,
        )
