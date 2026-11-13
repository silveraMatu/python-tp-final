"""Conversión de objetos de dominio a modelos de la API."""

from __future__ import annotations

from typing import List

from app.agent import replies
from app.agent.service import AgentReply
from app.api.access import EDITABLE
from app.api.auth import ApiUser, Role
from app.api.schemas import (
    ContractOut,
    DocumentLinkOut,
    FieldValueOut,
    MessageOut,
    PendingConflictOut,
)
from app.repositories.chat import ChatMessage
from app.schemas.contract import ContractData, ContractStatus


def allowed_actions(contract: ContractData, user: ApiUser) -> List[str]:
    """Acciones que el usuario puede hacer ahora sobre el contrato (pista para la UI)."""
    status = contract.status
    actions: List[str] = []
    if user.role is Role.REQUESTER and contract.created_by == user.name:
        if status in EDITABLE:
            actions.append("send_message")
            if replies.pending_conflicts(contract):
                actions.append("resolve_conflict")
            if contract.is_complete:
                actions.append("get_draft")
                if status is ContractStatus.COLLECTING_DATA:
                    actions.append("submit_for_review")
        elif status is ContractStatus.PENDING_HUMAN_REVIEW:
            actions.append("get_draft")
    if user.role is Role.REVIEWER and status is ContractStatus.PENDING_HUMAN_REVIEW:
        actions.extend(["get_draft", "review"])
    if status is ContractStatus.APPROVED:
        actions.extend(["get_final_document", "verify_final"])
    return actions


def contract_out(contract: ContractData, user: ApiUser) -> ContractOut:
    """Estado del contrato con los datos formateados para mostrar."""
    return ContractOut(
        id=contract.id,
        status=contract.status,
        status_label=replies.STATUS_LABELS[contract.status],
        created_by=contract.created_by,
        is_complete=contract.is_complete,
        missing_fields=contract.get_missing_fields(),
        fields=[
            FieldValueOut(
                field_name=path,
                label=replies.label(path),
                value=replies.display_value(path, contract.collected_values[path]),
            )
            for path in replies.FIELD_LABELS
            if path in contract.collected_values
        ],
        pending_conflicts=[
            PendingConflictOut(
                field_name=flag.field_name,
                label=replies.label(flag.field_name),
                value=replies.display_value(flag.field_name, flag.value_extracted),
                detail=flag.conflict_detail,
            )
            for flag in replies.pending_conflicts(contract)
        ],
        issues=replies.section_errors(contract),
        allowed_actions=allowed_actions(contract, user),
    )


def message_out(
    reply: AgentReply,
    contract: ContractData,
    user: ApiUser,
    user_message: ChatMessage,
    agent_message: ChatMessage,
) -> MessageOut:
    """Respuesta del agente sin exponer rutas del servidor (solo enlaces de descarga)."""
    documents = (
        [
            DocumentLinkOut(
                kind="draft",
                format="pdf",
                url=f"/contracts/{contract.id}/document?version=draft&format=pdf",
            )
        ]
        if reply.artifacts
        else []
    )
    return MessageOut(
        reply=reply.text,
        intent=reply.intent.value,
        classification_source=reply.classification_source,
        contract=contract_out(contract, user),
        documents=documents,
        sources=reply.sources,
        user_message=user_message,
        agent_message=agent_message,
    )
