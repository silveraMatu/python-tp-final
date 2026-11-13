"""Salud, identidad, plantillas y consultas a la documentación."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ServicesDep, UserDep
from app.api.schemas import KnowledgeAnswerOut, KnowledgeQueryIn, MeOut, TemplateOut
from app.services.template_catalog import list_templates

router = APIRouter(tags=["general"])


@router.get("/health")
def health() -> dict[str, str]:
    """Estado del servicio (sin autenticación)."""
    return {"status": "ok"}


@router.get("/me", response_model=MeOut)
def me(user: UserDep) -> MeOut:
    """Usuario autenticado y su rol."""
    return MeOut(name=user.name, role=user.role.value)


@router.get("/templates", response_model=List[TemplateOut])
def templates(user: UserDep) -> List[TemplateOut]:
    """Plantillas por modalidad: cuáles están aprobadas y qué campos exigen."""
    return [
        TemplateOut(
            modality=info.modality.value,
            label=info.label,
            available=info.available,
            required_fields=list(info.required_fields),
        )
        for info in list_templates()
    ]


@router.post("/knowledge/query", response_model=KnowledgeAnswerOut)
def query_knowledge(
    body: KnowledgeQueryIn, user: UserDep, services: ServicesDep
) -> KnowledgeAnswerOut:
    """Consulta la documentación institucional y las cláusulas aprobadas (con fuentes)."""
    if services.rag is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "La consulta de documentación no está disponible"
        )
    result = services.rag.answer(body.question)
    return KnowledgeAnswerOut(
        answer=result.answer,
        found=result.found,
        sources=list(dict.fromkeys(hit.source for hit in result.sources)),
    )
