"""Raíz de composición: cablea repositorio, servicios, agente y exportación."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.agent.intents import IntentClassifier
from app.agent.service import AgentService
from app.core.config import Settings
from app.security.output_guard import OutputGuard
from app.repositories.sqlite import SqliteContractRepository
from app.repositories.sqlite_chat import SqliteChatRepository
from app.services.attachment_store import AttachmentStore
from app.services.chat_service import ChatService
from app.services.contract_service import ContractService
from app.services.document_loader import DocumentLoader
from app.services.export_service import ExportService, build_export_service
from app.services.extraction_service import ExtractionService
from app.services.llm_client import build_llm_client
from app.services.rag_service import RagService, build_rag_service
from app.services.template_service import ContractTemplateService
from app.services.validation_service import ValidationService


@dataclass(frozen=True)
class Services:
    """Servicios de la aplicación, listos para usar."""

    settings: Settings
    contracts: ContractService
    templates: ContractTemplateService
    exporter: ExportService
    agent: AgentService
    loader: DocumentLoader
    rag: Optional[RagService]
    chat: ChatService


def build_services(settings: Settings, with_rag: bool = True) -> Services:
    """Construye todos los servicios a partir de la configuración."""
    llm = build_llm_client(settings)
    templates = ContractTemplateService(city=settings.city)
    contracts = ContractService(
        SqliteContractRepository(settings.database_path),
        ValidationService(settings.confidence_threshold),
        templates,
        settings.template_path,
    )
    exporter = build_export_service(settings, contracts, templates)
    rag = build_rag_service(settings) if with_rag else None
    agent = AgentService(
        contracts=contracts,
        extraction=ExtractionService(llm, max_retries=settings.extraction_max_retries),
        classifier=IntentClassifier(llm),
        rag=rag,
        exporter=exporter,
        output_guard=OutputGuard(settings.max_reply_chars),
        max_message_chars=settings.max_message_chars,
    )
    loader = DocumentLoader(
        max_bytes=settings.max_upload_bytes,
        max_pages=settings.max_document_pages,
        max_image_side=settings.max_image_side,
    )
    chat = ChatService(
        SqliteChatRepository(settings.database_path), AttachmentStore(settings.attachments_dir)
    )
    return Services(settings, contracts, templates, exporter, agent, loader, rag, chat)
