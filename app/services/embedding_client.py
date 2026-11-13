"""Puerto de embeddings y adaptador para Ollama (``nomic-embed-text``)."""

from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

import httpx
from ollama import Client, ResponseError

from app.core.config import Settings
from app.core.exceptions import LLMUnavailableError

Vector = List[float]


class EmbeddingClient(Protocol):
    """Convierte texto en vectores. Documentos y consultas se embeben distinto."""

    def embed_documents(self, texts: Sequence[str]) -> List[Vector]:
        """Un vector por texto, en el mismo orden.

        Raises:
            LLMUnavailableError: el servidor de embeddings no responde.
        """
        ...

    def embed_query(self, text: str) -> Vector:
        """Vector de una consulta."""
        ...


class OllamaEmbeddingClient:
    """Embeddings locales con Ollama.

    ``nomic-embed-text`` requiere un prefijo de tarea para rendir bien:
    ``search_document:`` al indexar y ``search_query:`` al consultar.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: float = 120.0,
        client: Optional[Client] = None,
    ) -> None:
        self._client = client if client is not None else Client(host=host, timeout=timeout)
        self._model = model

    def embed_documents(self, texts: Sequence[str]) -> List[Vector]:
        return self._embed([f"search_document: {text}" for text in texts])

    def embed_query(self, text: str) -> Vector:
        return self._embed([f"search_query: {text}"])[0]

    def _embed(self, inputs: List[str]) -> List[Vector]:
        if not inputs:
            return []
        try:
            response = self._client.embed(model=self._model, input=inputs)
        except ResponseError as exc:
            raise LLMUnavailableError(
                f"Ollama rechazó la solicitud de embeddings al modelo '{self._model}' "
                f"({exc.status_code}): {exc.error}"
            ) from exc
        except (httpx.HTTPError, ConnectionError, TimeoutError) as exc:
            raise LLMUnavailableError(f"No se pudo contactar a Ollama: {exc}") from exc

        vectors = [list(map(float, vector)) for vector in response.embeddings]
        if len(vectors) != len(inputs):
            raise LLMUnavailableError(
                f"Ollama devolvió {len(vectors)} embeddings para {len(inputs)} textos"
            )
        return vectors


def build_embedding_client(settings: Settings) -> OllamaEmbeddingClient:
    """Construye el cliente de embeddings a partir de la configuración."""
    return OllamaEmbeddingClient(
        host=settings.ollama_host, model=settings.embedding_model, timeout=settings.ollama_timeout
    )
