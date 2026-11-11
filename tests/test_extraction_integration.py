"""Pruebas contra un Ollama real. Ejecutar con: uv run pytest -m integration"""

from __future__ import annotations

import pymupdf
import pytest
from ollama import Client

from app.core.config import get_settings
from app.services.document_loader import DocumentLoader
from app.services.extraction_service import ExtractionService
from app.services.llm_client import OllamaClient

pytestmark = pytest.mark.integration

settings = get_settings()


def _installed_models() -> set[str]:
    try:
        return {m.model for m in Client(host=settings.ollama_host).list().models if m.model}
    except Exception:  # servidor apagado
        return set()


def _require(model: str) -> None:
    names = _installed_models()
    if model not in names and f"{model}:latest" not in names:
        pytest.skip(f"Modelo {model} no disponible en Ollama")


@pytest.fixture(scope="module")
def service() -> ExtractionService:
    llm = OllamaClient(
        host=settings.ollama_host,
        text_model=settings.ollama_text_model,
        vision_model=settings.ollama_vision_model,
        timeout=settings.ollama_timeout,
    )
    return ExtractionService(llm, max_retries=settings.extraction_max_retries)


def test_text_extraction(service: ExtractionService) -> None:
    _require(settings.ollama_text_model)
    result = service.extract_from_text(
        "Necesito un contrato para Juan Pérez, DNI 30.123.456, CUIL 20-30123456-3, "
        "nacido el 15/03/1995. Ingresa el 9 de noviembre de 2026 como Desarrollador de "
        "Software, por tiempo indeterminado, con un sueldo bruto de $ 2.500.000."
    )
    values = {c.field_name: c.value for c in result.candidates}
    assert values.get("employee.dni") == "30123456"
    assert values.get("employee.fecha_nacimiento") == "1995-03-15"
    assert values.get("terms.remuneracion_bruta") == "2500000"
    assert "employee.salario" not in values


def test_image_extraction(service: ExtractionService) -> None:
    _require(settings.ollama_vision_model)
    page_doc = pymupdf.open()
    page = page_doc.new_page(width=500, height=300)
    page.insert_text((30, 60), "DOCUMENTO NACIONAL DE IDENTIDAD (FICTICIO)", fontsize=12)
    page.insert_text((30, 110), "Apellido: PEREZ", fontsize=16)
    page.insert_text((30, 150), "Nombre: JUAN CARLOS", fontsize=16)
    page.insert_text((30, 190), "DNI: 30.123.456", fontsize=16)
    page.insert_text((30, 230), "Fecha de nacimiento: 15 MAR 1995", fontsize=16)
    png = page.get_pixmap(dpi=150).tobytes("png")

    document = DocumentLoader().load(bytes(png), "dni.png")
    result = service.extract_from_document(document)
    values = {c.field_name: c.value for c in result.candidates}
    assert values.get("employee.dni") == "30123456"
