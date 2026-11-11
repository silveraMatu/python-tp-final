"""Puerto de acceso al LLM y adaptador para Ollama."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, Sequence

import httpx
from ollama import Client, ResponseError

from app.core.exceptions import ExtractionError, LLMUnavailableError


class LLMClient(Protocol):
    """Genera JSON que cumple un JSON Schema. Es la única puerta hacia el modelo."""

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        images: Sequence[bytes] = (),
    ) -> str:
        """Devuelve el texto JSON de la respuesta.

        Raises:
            LLMUnavailableError: el servidor no responde o el modelo no está disponible.
        """
        ...


class OllamaClient:
    """Adaptador de :class:`LLMClient` sobre un servidor Ollama local.

    Usa el modelo de visión si hay imágenes y el de texto en caso contrario.
    La salida se restringe con ``format=<JSON Schema>`` y ``temperature=0`` para que
    sea lo más determinista posible.
    """

    def __init__(
        self,
        host: str = "http://localhost:11434",
        text_model: str = "qwen2.5vl:3b",
        vision_model: str = "qwen2.5vl:3b",
        timeout: float = 300.0,
        client: Optional[Client] = None,
    ) -> None:
        self._client = client if client is not None else Client(host=host, timeout=timeout)
        self._text_model = text_model
        self._vision_model = vision_model

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        images: Sequence[bytes] = (),
    ) -> str:
        model = self._vision_model if images else self._text_model
        user_message: dict[str, Any] = {"role": "user", "content": user}
        if images:
            user_message["images"] = list(images)
        try:
            response = self._client.chat(
                model=model,
                messages=[{"role": "system", "content": system}, user_message],
                format=dict(schema),
                options={"temperature": 0, "num_ctx": 8192},
            )
        except ResponseError as exc:
            raise LLMUnavailableError(
                f"Ollama rechazó la solicitud al modelo '{model}' ({exc.status_code}): {exc.error}"
            ) from exc
        except (httpx.HTTPError, ConnectionError, TimeoutError) as exc:
            raise LLMUnavailableError(f"No se pudo contactar a Ollama: {exc}") from exc

        content = response.message.content
        if not content:
            raise ExtractionError(f"El modelo '{model}' devolvió una respuesta vacía")
        return str(content)
