from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from ollama import ResponseError

from app.core.exceptions import ExtractionError, LLMUnavailableError
from app.core.config import Settings
from app.services.llm_client import OllamaClient, build_llm_client

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
    assert fake.kwargs["options"] == {"temperature": 0, "num_predict": 1024}
    assert fake.kwargs["think"] is False
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


def test_think_flag_is_forwarded() -> None:
    fake = FakeOllama()
    OllamaClient(client=fake, think=True).generate_json(system="s", user="u", schema=SCHEMA)  # type: ignore[arg-type]
    assert fake.kwargs["think"] is True


def test_payment_required_mentions_credits() -> None:
    fake = FakeOllama(error=ResponseError("Add usage credits or subscribe", 402))
    with pytest.raises(LLMUnavailableError, match="créditos") as info:
        make(fake).generate_json(system="s", user="u", schema=SCHEMA)
    assert "402" in str(info.value)


def test_build_llm_client_uses_settings() -> None:
    settings = Settings(
        ollama_text_model="t", ollama_vision_model="v", ollama_think=True, _env_file=None
    )
    client = build_llm_client(settings)
    assert (client._text_model, client._vision_model, client._think) == ("t", "v", True)


def test_default_models_are_deepseek_cloud() -> None:
    settings = Settings(_env_file=None)
    assert settings.ollama_text_model == settings.ollama_vision_model == "deepseek-v4.1-flash:cloud"
    assert settings.ollama_think is False


def test_response_error_becomes_llm_unavailable() -> None:
    fake = FakeOllama(error=ResponseError("model 'vis' not found", 404))
    with pytest.raises(LLMUnavailableError, match="404"):
        make(fake).generate_json(system="s", user="u", schema=SCHEMA)


def test_empty_response_is_an_extraction_error() -> None:
    with pytest.raises(ExtractionError):
        make(FakeOllama(content="")).generate_json(system="s", user="u", schema=SCHEMA)
