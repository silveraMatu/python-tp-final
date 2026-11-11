from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from ollama import ResponseError

from app.core.exceptions import ExtractionError, LLMUnavailableError
from app.services.llm_client import OllamaClient

SCHEMA = {"type": "object"}


class FakeOllama:
    def __init__(self, content: str | None = '{"fields": []}', error: Exception | None = None):
        self.content = content
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def chat(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(message=SimpleNamespace(content=self.content))


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient(text_model="txt", vision_model="vis", client=fake)  # type: ignore[arg-type]


def test_text_call_uses_text_model_and_schema() -> None:
    fake = FakeOllama()
    out = make(fake).generate_json(system="s", user="u", schema=SCHEMA)
    assert out == '{"fields": []}'
    assert fake.kwargs["model"] == "txt"
    assert fake.kwargs["format"] == SCHEMA
    assert fake.kwargs["options"]["temperature"] == 0
    assert fake.kwargs["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


def test_images_switch_to_vision_model() -> None:
    fake = FakeOllama()
    make(fake).generate_json(system="s", user="u", schema=SCHEMA, images=[b"img"])
    assert fake.kwargs["model"] == "vis"
    assert fake.kwargs["messages"][1]["images"] == [b"img"]


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError("refused"), ConnectionError("down"), TimeoutError("slow")],
)
def test_connection_errors_become_llm_unavailable(error: Exception) -> None:
    with pytest.raises(LLMUnavailableError):
        make(FakeOllama(error=error)).generate_json(system="s", user="u", schema=SCHEMA)


def test_response_error_becomes_llm_unavailable() -> None:
    fake = FakeOllama(error=ResponseError("model 'vis' not found", 404))
    with pytest.raises(LLMUnavailableError, match="404"):
        make(fake).generate_json(system="s", user="u", schema=SCHEMA)


def test_empty_response_is_an_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        make(FakeOllama(content="")).generate_json(system="s", user="u", schema=SCHEMA)
