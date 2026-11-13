"""Fachada del agente: un turno de conversación = un ``handle_message``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from uuid import UUID

from app.agent import replies
from app.agent.graph import AgentState, ContractAgentGraph
from app.agent.guardrails import truncate
from app.agent.intents import Intent, IntentClassifier
from app.core.config import Settings
from app.repositories.sqlite import SqliteContractRepository
from app.schemas.contract import ContractData, ContractStatus
from app.services.contract_service import ContractService
from app.services.document_loader import LoadedDocument
from app.services.export_service import ExportService, build_export_service
from app.services.extraction_service import ExtractionService
from app.services.llm_client import build_llm_client
from app.services.rag_service import RagService, build_rag_service
from app.services.template_service import ContractTemplateService
from app.services.validation_service import ValidationService


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
    ) -> None:
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
        state: AgentState = {
            "contract_id": contract_id,
            "actor": actor,
            "message": truncate(message),
            "documents": tuple(documents),
            "parts": [],
            "artifacts": [],
            "sources": [],
        }
        final = self._graph.invoke(state)

        contract = self._contracts.get(contract_id)
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
            text=final["reply"],
            intent=final["intent"],
            status=contract.status,
            missing_fields=contract.get_missing_fields(),
            pending_conflicts=conflicts,
            artifacts=list(final.get("artifacts", [])),
            sources=list(dict.fromkeys(final.get("sources", []))),
            classification_source=final.get("classification_source", ""),
        )


def build_agent_service(settings: Settings, with_rag: bool = True) -> AgentService:
    """Cablea repositorio, servicios y LLM según la configuración."""
    llm = build_llm_client(settings)
    templates = ContractTemplateService(city=settings.city)
    contracts = ContractService(
        SqliteContractRepository(settings.database_path),
        ValidationService(settings.confidence_threshold),
        templates,
        settings.template_path,
    )
    return AgentService(
        contracts=contracts,
        extraction=ExtractionService(llm, max_retries=settings.extraction_max_retries),
        classifier=IntentClassifier(llm),
        rag=build_rag_service(settings) if with_rag else None,
        exporter=build_export_service(settings, contracts, templates),
    )
