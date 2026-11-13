"""RAG contra Ollama real (embeddings locales + DeepSeek cloud).

Ejecutar con: uv run pytest -m integration
Se omite si el modelo de embeddings o el LLM no están disponibles.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings
from app.core.exceptions import LLMUnavailableError
from app.services.embedding_client import build_embedding_client
from app.services.llm_client import build_llm_client
from app.services.rag_service import RagService

pytestmark = pytest.mark.integration


@pytest.fixture
def service(tmp_path: Path) -> RagService:
    settings = get_settings()
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "politica.txt").write_text(
        "Política interna de licencias.\n\nLas licencias por examen se solicitan con cinco "
        "días hábiles de anticipación y requieren constancia de la institución educativa.",
        encoding="utf-8",
    )
    rag = RagService(
        embedder=build_embedding_client(settings),
        llm=build_llm_client(settings),
        chroma=chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False)),
        knowledge_dir=knowledge,
        collection_name=f"it-{uuid.uuid4().hex}",
        top_k=settings.rag_top_k,
        min_score=settings.rag_min_score,
    )
    try:
        rag.rebuild()
    except LLMUnavailableError as exc:
        pytest.skip(f"Embeddings no disponibles: {exc}")
    return rag


def test_answers_from_clause_with_citation(service: RagService) -> None:
    try:
        result = service.answer("¿Qué dice el contrato sobre la confidencialidad?")
    except LLMUnavailableError as exc:
        pytest.skip(f"LLM no disponible: {exc}")
    assert result.found
    assert "clausula:SEXTA" in {hit.source for hit in result.sources}


def test_answers_from_added_document(service: RagService) -> None:
    try:
        result = service.answer("¿Con cuánta anticipación se piden las licencias por examen?")
    except LLMUnavailableError as exc:
        pytest.skip(f"LLM no disponible: {exc}")
    assert result.found and "cinco" in result.answer.lower()
    assert "politica.txt" in {hit.source for hit in result.sources}


def test_unknown_topic_is_not_invented(service: RagService) -> None:
    try:
        result = service.answer("¿Cuántos días de vacaciones corresponden por antigüedad?")
    except LLMUnavailableError as exc:
        pytest.skip(f"LLM no disponible: {exc}")
    assert not result.found
