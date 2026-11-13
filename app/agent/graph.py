"""Grafo LangGraph del agente conversacional.

El flujo es fijo: ``classify`` decide la intención (guardrails, atajos o LLM con
salida restringida) y una arista condicional enruta a un nodo que ejecuta la acción
llamando a los servicios. ``compose`` agrega el siguiente paso desde el estado del
contrato. El LLM nunca redacta texto sobre el contrato y este grafo no tiene
acceso a ``review``/``mark_as_reviewed``: no puede aprobar ni rechazar.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, Sequence, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agent import replies
from app.agent.guardrails import REFUSAL_APPROVAL, REFUSAL_CLAUSES
from app.agent.intents import Classification, Intent, IntentClassifier
from app.core.exceptions import (
    ContractRenderError,
    ExtractionError,
    IncompleteContractDataError,
    InvalidStateTransitionError,
    UnsupportedModalityError,
)
from app.schemas.contract import ContractStatus, EmploymentType
from app.schemas.extraction import FieldCandidate
from app.services.contract_service import ContractService
from app.services.document_loader import LoadedDocument
from app.services.export_service import ExportService
from app.services.extraction_service import ExtractionService
from app.services.rag_service import RagService
from app.services.template_catalog import get_template_info

_EDITABLE = frozenset(
    {ContractStatus.INITIAL, ContractStatus.COLLECTING_DATA, ContractStatus.CONFLICT_DETECTED}
)


class AgentState(TypedDict, total=False):
    """Estado de un turno. El estado del contrato NO vive aquí: se lee del servicio."""

    contract_id: UUID
    actor: str
    message: str
    documents: Sequence[LoadedDocument]
    intent: Intent
    decision: Optional[str]
    classification_source: str
    parts: Annotated[List[str], operator.add]
    artifacts: Annotated[List[str], operator.add]
    sources: Annotated[List[str], operator.add]
    reply: str


class ContractAgentGraph:
    """Construye y compila el grafo con sus dependencias."""

    def __init__(
        self,
        contracts: ContractService,
        extraction: ExtractionService,
        classifier: IntentClassifier,
        rag: Optional[RagService],
        exporter: ExportService,
    ) -> None:
        self._contracts = contracts
        self._extraction = extraction
        self._classifier = classifier
        self._rag = rag
        self._exporter = exporter

    def compile(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("classify", self._classify)
        graph.add_node("provide_data", self._provide_data)
        graph.add_node("resolve_conflict", self._resolve_conflict)
        graph.add_node("ask_info", self._ask_info)
        graph.add_node("submit_review", self._submit_review)
        graph.add_node("show_status", self._show_status)
        graph.add_node("show_draft", self._show_draft)
        graph.add_node("refuse", self._refuse)
        graph.add_node("small_talk", self._small_talk)
        graph.add_node("compose", self._compose)

        graph.add_edge(START, "classify")
        graph.add_conditional_edges(
            "classify",
            self._route,
            {
                Intent.PROVIDE_DATA.value: "provide_data",
                Intent.RESOLVE_CONFLICT.value: "resolve_conflict",
                Intent.ASK_INFO.value: "ask_info",
                Intent.SUBMIT_REVIEW.value: "submit_review",
                Intent.SHOW_STATUS.value: "show_status",
                Intent.SHOW_DRAFT.value: "show_draft",
                Intent.APPROVE_OR_SIGN.value: "refuse",
                Intent.EDIT_CLAUSES.value: "refuse",
                Intent.SMALL_TALK.value: "small_talk",
            },
        )
        for node in (
            "provide_data",
            "resolve_conflict",
            "ask_info",
            "submit_review",
            "show_status",
            "show_draft",
            "refuse",
            "small_talk",
        ):
            graph.add_edge(node, "compose")
        graph.add_edge("compose", END)
        return graph.compile()

    # ------------------------------------------------------------------ #
    # Enrutamiento
    # ------------------------------------------------------------------ #

    @staticmethod
    def _route(state: AgentState) -> str:
        return state["intent"].value

    def _classify(self, state: AgentState) -> Dict[str, Any]:
        message = state.get("message", "").strip()
        documents = state.get("documents", ())
        if not message:
            intent = Intent.PROVIDE_DATA if documents else Intent.SMALL_TALK
            return {"intent": intent, "decision": None, "classification_source": "no-text"}

        contract = self._contracts.get(state["contract_id"])
        conflicts = replies.pending_conflicts(contract)
        pending_label = replies.label(conflicts[0].field_name) if conflicts else None
        result: Classification = self._classifier.classify(message, pending_label)

        intent = result.intent
        if documents and intent is Intent.SMALL_TALK:
            intent = Intent.PROVIDE_DATA  # un adjunto con un saludo sigue siendo datos
        return {
            "intent": intent,
            "decision": result.decision,
            "classification_source": result.source,
        }

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #

    def _provide_data(self, state: AgentState) -> Dict[str, Any]:
        contract_id = state["contract_id"]
        contract = self._contracts.get(contract_id)
        if contract.status not in _EDITABLE:
            return {"parts": [self._locked_message(contract.status)]}

        candidates: List[FieldCandidate] = []
        parts: List[str] = []
        warnings: List[str] = []

        message = state.get("message", "").strip()
        jobs: List[tuple[str, Any]] = []
        if message:
            jobs.append(("tu mensaje", lambda: self._extraction.extract_from_text(message)))
        for document in state.get("documents", ()):
            jobs.append(
                (
                    f"«{document.filename}»",
                    lambda document=document: self._extraction.extract_from_document(document),
                )
            )
        for name, job in jobs:
            try:
                result = job()
            except ExtractionError:
                parts.append(f"No pude interpretar {name}. ¿Podés reenviarlo o escribir los datos?")
                continue
            candidates.extend(result.candidates)
            warnings.extend(result.warnings)

        if not candidates:
            return {"parts": parts or [replies.NO_DATA_FOUND]}

        applied = self._contracts.apply_extraction(contract_id, candidates, state["actor"])
        if applied.accepted:
            parts.append(
                f"Registré {len(applied.accepted)} dato(s):\n"
                + "\n".join(
                    f"- {replies.label(path)}: "
                    f"{replies.display_value(path, applied.contract.collected_values[path])}"
                    for path in applied.accepted
                )
            )
        if applied.conflicts:
            parts.append(
                f"{len(applied.conflicts)} dato(s) quedaron pendientes de tu confirmación: "
                + ", ".join(replies.label(path) for path in applied.conflicts)
                + "."
            )
        for path, reason in applied.rejected.items():
            parts.append(f"No pude usar «{replies.label(path)}»: {reason}.")
        parts.extend(self._pretty_warning(warning) for warning in warnings)

        modality_note = self._modality_note(applied.contract.collected_values.get("terms.modalidad"))
        if modality_note:
            parts.append(modality_note)
        return {"parts": parts}

    def _resolve_conflict(self, state: AgentState) -> Dict[str, Any]:
        contract_id = state["contract_id"]
        contract = self._contracts.get(contract_id)
        conflicts = replies.pending_conflicts(contract)
        if not conflicts:
            return {"parts": [replies.NO_PENDING_CONFLICT]}
        decision = state.get("decision")
        if decision not in ("accept", "keep"):
            return {"parts": [replies.CONFIRMATION_UNCLEAR]}

        flag = conflicts[0]
        accept = decision == "accept"
        self._contracts.resolve_conflict(contract_id, flag.field_name, accept, state["actor"])
        name = replies.label(flag.field_name)
        if accept:
            value = replies.display_value(flag.field_name, flag.value_extracted)
            return {"parts": [f"Listo, usé «{value}» para {name}."]}
        return {"parts": [f"Listo, descarté el valor leído para {name}."]}

    def _ask_info(self, state: AgentState) -> Dict[str, Any]:
        if self._rag is None:
            return {"parts": [replies.RAG_UNAVAILABLE]}
        answer = self._rag.answer(state.get("message", ""))
        return {
            "parts": [answer.answer],
            "sources": [f"{hit.source}" for hit in answer.sources],
        }

    def _submit_review(self, state: AgentState) -> Dict[str, Any]:
        contract_id = state["contract_id"]
        try:
            self._contracts.submit_for_review(contract_id, state["actor"])
        except InvalidStateTransitionError as exc:
            contract = self._contracts.get(contract_id)
            if contract.status is ContractStatus.PENDING_HUMAN_REVIEW:
                return {"parts": ["El borrador ya está pendiente de revisión humana."]}
            reason = (
                "hay datos por confirmar"
                if replies.pending_conflicts(contract)
                else exc.message
            )
            return {"parts": [f"Todavía no puedo enviarlo a revisión: {reason}."]}
        return {
            "parts": [
                "Envié el borrador a revisión humana. Un responsable autorizado deberá "
                "aprobarlo o rechazarlo; yo no puedo hacerlo."
            ]
        }

    def _show_status(self, state: AgentState) -> Dict[str, Any]:
        return {"parts": [replies.summary(self._contracts.get(state["contract_id"]))]}

    def _show_draft(self, state: AgentState) -> Dict[str, Any]:
        try:
            document = self._exporter.export_draft(state["contract_id"], state["actor"])
        except IncompleteContractDataError:
            return {"parts": ["Todavía no puedo generar el borrador: faltan datos o hay errores."]}
        except UnsupportedModalityError as exc:
            return {"parts": [f"No puedo generar el borrador: {exc.message}."]}
        except InvalidStateTransitionError:
            return {"parts": ["Este contrato ya tuvo una decisión: no admite un nuevo borrador."]}
        except ContractRenderError as exc:
            return {"parts": [f"No pude generar el documento: {exc.message}"]}
        return {
            "parts": [
                "Generé la versión preliminar en PDF, con marca de BORRADOR. Es solo para "
                "revisar: no está aprobada ni formalizada."
            ],
            "artifacts": [str(document.pdf_path)],
        }

    @staticmethod
    def _refuse(state: AgentState) -> Dict[str, Any]:
        if state["intent"] is Intent.APPROVE_OR_SIGN:
            return {"parts": [REFUSAL_APPROVAL]}
        return {"parts": [REFUSAL_CLAUSES]}

    def _small_talk(self, state: AgentState) -> Dict[str, Any]:
        contract = self._contracts.get(state["contract_id"])
        initial = contract.status is ContractStatus.INITIAL
        return {"parts": [replies.WELCOME if initial else replies.NOT_UNDERSTOOD]}

    def _compose(self, state: AgentState) -> Dict[str, Any]:
        parts = list(state.get("parts", []))
        if state["intent"] is not Intent.ASK_INFO:
            parts.append(replies.next_step(self._contracts.get(state["contract_id"])))
        return {"reply": "\n\n".join(part for part in parts if part)}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _locked_message(status: ContractStatus) -> str:
        if status is ContractStatus.PENDING_HUMAN_REVIEW:
            return replies.LOCKED_PENDING
        return replies.LOCKED_CLOSED.format(status=replies.STATUS_LABELS[status].lower())

    @staticmethod
    def _pretty_warning(warning: str) -> str:
        path, separator, rest = warning.partition(": ")
        if separator and path in replies.FIELD_LABELS:
            return f"Aviso sobre «{replies.label(path)}»: {rest}."
        return f"Aviso: {warning}."

    @staticmethod
    def _modality_note(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        try:
            info = get_template_info(EmploymentType(str(value)))
        except ValueError:
            return None
        if info.available:
            return None
        return (
            f"Ojo: para «{info.label}» todavía no hay una plantilla aprobada, así que no podré "
            "generar el documento. Hoy solo está disponible el contrato por tiempo indeterminado."
        )
