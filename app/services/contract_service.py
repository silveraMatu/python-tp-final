"""Casos de uso del contrato.

Es el único componente que muta :class:`ContractData` y lo persiste. El agente y la
API lo invocan; el LLM nunca escribe directamente sobre el estado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence
from uuid import UUID

from app.core.exceptions import ConflictNotFoundError, InvalidStateTransitionError
from app.domain.state_machine import transition
from app.repositories.base import AuditEntry, ContractRepository
from app.schemas.contract import (
    ContractData,
    ContractStatus,
    FieldValidation,
    ValidationSeverity,
)
from app.schemas.extraction import FieldCandidate
from app.services.template_service import ContractTemplateService, RenderOptions
from app.services.validation_service import (
    SECTION_MODELS,
    Outcome,
    ValidationService,
    accepted_flag,
)

_EDITABLE_STATES = frozenset(
    {ContractStatus.INITIAL, ContractStatus.COLLECTING_DATA, ContractStatus.CONFLICT_DETECTED}
)


@dataclass(frozen=True)
class ApplyResult:
    """Resumen de aplicar un lote de candidatos."""

    contract: ContractData
    accepted: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)

    @property
    def missing_fields(self) -> List[str]:
        return self.contract.missing_fields


class ContractService:
    """Orquesta validación, estado, persistencia y generación del documento."""

    def __init__(
        self,
        repository: ContractRepository,
        validator: ValidationService,
        templates: ContractTemplateService,
        template_path: str | Path,
    ) -> None:
        self._repo = repository
        self._validator = validator
        self._templates = templates
        self._template_path = str(template_path)

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #

    def get(self, contract_id: UUID) -> ContractData:
        return self._repo.get(contract_id)

    def list(self, status: Optional[ContractStatus] = None) -> List[ContractData]:
        return self._repo.list(status)

    def history(self, contract_id: UUID) -> List[AuditEntry]:
        return self._repo.history(contract_id)

    # ------------------------------------------------------------------ #
    # Casos de uso
    # ------------------------------------------------------------------ #

    def start(self, actor: str) -> ContractData:
        """Crea un borrador vacío en estado ``INITIAL``."""
        contract = ContractData(created_by=actor)
        contract.get_missing_fields()
        self._repo.create(contract, actor)
        return contract

    def apply_extraction(
        self, contract_id: UUID, candidates: Sequence[FieldCandidate], actor: str
    ) -> ApplyResult:
        """Valida y aplica un lote de datos extraídos.

        - Aceptados: pasan a ``collected_values``.
        - En conflicto (valor distinto o baja confianza): quedan pendientes de
          confirmación y el contrato pasa a ``CONFLICT_DETECTED``.
        - Rechazados (inválidos o desconocidos): no se aplican.

        Raises:
            InvalidStateTransitionError: el contrato ya no admite cambios de datos.
        """
        contract = self._repo.get(contract_id)
        if contract.status not in _EDITABLE_STATES:
            raise InvalidStateTransitionError(
                contract.status.value,
                ContractStatus.COLLECTING_DATA.value,
                "el contrato no admite cambios de datos en este estado",
            )
        if contract.status is ContractStatus.INITIAL:
            transition(contract, ContractStatus.COLLECTING_DATA)

        accepted: List[str] = []
        conflicts: List[str] = []
        rejected: dict[str, str] = {}

        for candidate in candidates:
            evaluation = self._validator.evaluate(contract, candidate)
            path = candidate.field_name
            if evaluation.outcome is Outcome.ACCEPTED:
                if not evaluation.unchanged:
                    contract.collected_values[path] = candidate.value
                    self._upsert_flag(contract, evaluation.flag)
                    accepted.append(path)
            elif evaluation.outcome is Outcome.CONFLICT:
                self._upsert_flag(contract, evaluation.flag)
                conflicts.append(path)
            else:
                rejected[path] = evaluation.flag.conflict_detail or "valor inválido"
                # Un rechazo no pisa un valor ya aceptado; solo se deja constancia si no hay ninguno.
                if path not in contract.collected_values:
                    self._upsert_flag(contract, evaluation.flag)

        self._refresh(contract)
        self._repo.save(
            contract,
            actor,
            "extraction_applied",
            f"aceptados={len(accepted)} conflictos={len(conflicts)} rechazados={len(rejected)}",
        )
        return ApplyResult(contract, accepted, conflicts, rejected)

    def resolve_conflict(
        self, contract_id: UUID, field_name: str, accept_new: bool, actor: str
    ) -> ContractData:
        """Resuelve un conflicto pendiente con la decisión del usuario.

        Args:
            accept_new: True adopta el valor pendiente; False conserva el valor previo
                (o descarta el dato si nunca hubo uno aceptado).

        Raises:
            ConflictNotFoundError: el campo no tiene un conflicto pendiente.
        """
        contract = self._repo.get(contract_id)
        flag = self._find_flag(contract, field_name)
        if flag is None or not flag.conflict_detected:
            raise ConflictNotFoundError(field_name)

        if accept_new:
            contract.collected_values[field_name] = flag.value_extracted
            self._upsert_flag(contract, accepted_flag(field_name, flag.value_extracted))
        elif field_name in contract.collected_values:
            self._upsert_flag(
                contract, accepted_flag(field_name, contract.collected_values[field_name])
            )
        else:
            contract.validation_flags.remove(flag)

        self._refresh(contract)
        self._repo.save(
            contract,
            actor,
            "conflict_accepted" if accept_new else "conflict_rejected",
            field_name,
        )
        return contract

    def submit_for_review(self, contract_id: UUID, actor: str) -> ContractData:
        """Envía el borrador a revisión humana (requiere completo y sin conflictos)."""
        contract = self._repo.get(contract_id)
        transition(contract, ContractStatus.PENDING_HUMAN_REVIEW)
        self._repo.save(contract, actor, "submitted_for_review")
        return contract

    def review(
        self, contract_id: UUID, approved: bool, actor: str, comment: Optional[str] = None
    ) -> ContractData:
        """Registra la decisión del revisor humano (con un comentario opcional en la auditoría).

        Raises:
            InvalidStateTransitionError: no está pendiente de revisión o no cumple
                las condiciones para aprobarse.
        """
        contract = self._repo.get(contract_id)
        target = ContractStatus.APPROVED if approved else ContractStatus.REJECTED
        try:
            contract.mark_as_reviewed(approved)
        except ValueError as exc:
            raise InvalidStateTransitionError(
                contract.status.value, target.value, str(exc)
            ) from exc
        self._repo.save(contract, actor, "approved" if approved else "rejected", comment)
        return contract

    def request_changes(
        self, contract_id: UUID, actor: str, comment: Optional[str] = None
    ) -> ContractData:
        """El revisor devuelve el borrador a la recolección de datos."""
        contract = self._repo.get(contract_id)
        transition(contract, ContractStatus.COLLECTING_DATA)
        self._repo.save(contract, actor, "changes_requested", comment)
        return contract

    def render(
        self,
        contract_id: UUID,
        output_path: str,
        actor: str,
        require_approved: bool = False,
    ) -> str:
        """Genera el .docx del contrato y devuelve su ruta absoluta.

        Args:
            require_approved: exige estado ``APPROVED`` (documento final); con False
                se permite generar una versión preliminar de un contrato completo.

        Raises:
            InvalidStateTransitionError: se pidió el documento final sin aprobación.
            IncompleteContractDataError: el contrato no está completo.
        """
        contract = self._repo.get(contract_id)
        if require_approved and contract.status is not ContractStatus.APPROVED:
            raise InvalidStateTransitionError(
                contract.status.value,
                ContractStatus.APPROVED.value,
                "el documento final requiere un contrato aprobado",
            )
        path = self._templates.render_contract(
            contract, self._template_path, output_path, RenderOptions(draft=not require_approved)
        )
        self._repo.save(
            contract, actor, "rendered_final" if require_approved else "rendered_draft"
        )
        return path

    def record_event(
        self, contract_id: UUID, actor: str, action: str, detail: Optional[str] = None
    ) -> None:
        """Agrega una entrada de auditoría sin modificar el contrato."""
        self._repo.save(self._repo.get(contract_id), actor, action, detail)

    # ------------------------------------------------------------------ #
    # Helpers internos
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_flag(contract: ContractData, field_name: str) -> Optional[FieldValidation]:
        return next((f for f in contract.validation_flags if f.field_name == field_name), None)

    def _upsert_flag(self, contract: ContractData, flag: FieldValidation) -> None:
        """Mantiene un único flag (el más reciente) por campo."""
        existing = self._find_flag(contract, flag.field_name)
        if existing is None:
            contract.validation_flags.append(flag)
        else:
            contract.validation_flags[contract.validation_flags.index(existing)] = flag

    def _refresh(self, contract: ContractData) -> None:
        """Reensambla secciones, errores de sección, faltantes y estado."""
        assembly = self._validator.assemble(contract.collected_values)
        for section in SECTION_MODELS:
            setattr(contract, section, assembly.sections[section])
            stale = self._find_flag(contract, section)
            if stale is not None:
                contract.validation_flags.remove(stale)
            if section in assembly.errors:
                contract.validation_flags.append(
                    FieldValidation(
                        field_name=section,
                        is_valid=False,
                        confidence_score=1.0,
                        conflict_detected=False,
                        conflict_detail=assembly.errors[section],
                        severity=ValidationSeverity.ERROR,
                    )
                )
        contract.get_missing_fields()

        if contract.status is ContractStatus.COLLECTING_DATA and contract.has_conflicts():
            transition(contract, ContractStatus.CONFLICT_DETECTED)
        elif contract.status is ContractStatus.CONFLICT_DETECTED and not contract.has_conflicts():
            transition(contract, ContractStatus.COLLECTING_DATA)
