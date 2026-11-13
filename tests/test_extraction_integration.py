"""Pruebas contra un Ollama real (DeepSeek cloud por defecto).

Ejecutar con: uv run pytest -m integration
Se omiten si el modelo no responde (sin red, sin créditos, modelo no descargado).
Usar solo datos ficticios.
"""

from __future__ import annotations

import pymupdf
import pytest

from app.core.config import get_settings
from app.core.exceptions import LLMUnavailableError
from app.services.document_loader import DocumentLoader
from app.services.extraction_service import ExtractionResult, ExtractionService
from app.services.llm_client import build_llm_client

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def service() -> ExtractionService:
    settings = get_settings()
    return ExtractionService(
        build_llm_client(settings), max_retries=settings.extraction_max_retries
    )


def _values(result: ExtractionResult) -> dict[str, str]:
    return {str(c.field_name): str(c.value) for c in result.candidates}


def _skip_if_unavailable(error: LLMUnavailableError) -> None:
    pytest.skip(f"Modelo no disponible: {error}")


def test_text_extraction(service: ExtractionService) -> None:
    try:
        result = service.extract_from_text(
            "Necesito un contrato para Juan Pérez, DNI 30.123.456, CUIL 20-30123456-3, "
            "nacido el 15/03/1995. Ingresa el 9 de noviembre de 2026 como Desarrollador de "
            "Software, por tiempo indeterminado, con un sueldo bruto de $ 2.500.000."
        )
    except LLMUnavailableError as exc:
        return _skip_if_unavailable(exc)

    values = _values(result)
    assert values.get("employee.dni") == "30123456"
    assert values.get("employee.cuil") == "20301234563"
    assert values.get("employee.fecha_nacimiento") == "1995-03-15"
    assert values.get("terms.fecha_inicio") == "2026-11-09"
    assert values.get("terms.modalidad") == "INDETERMINATE"
    assert values.get("terms.remuneracion_bruta") == "2500000"
    assert result.warnings == []


def test_image_extraction(service: ExtractionService) -> None:
    page_doc = pymupdf.open()
    page = page_doc.new_page(width=500, height=300)
    page.insert_text((30, 60), "DOCUMENTO NACIONAL DE IDENTIDAD (FICTICIO)", fontsize=12)
    page.insert_text((30, 110), "Apellido: PEREZ", fontsize=16)
    page.insert_text((30, 150), "Nombre: JUAN CARLOS", fontsize=16)
    page.insert_text((30, 190), "DNI: 30.123.456", fontsize=16)
    page.insert_text((30, 230), "Fecha de nacimiento: 15 MAR 1995", fontsize=16)
    png = bytes(page.get_pixmap(dpi=150).tobytes("png"))

    document = DocumentLoader().load(png, "dni.png")
    try:
        result = service.extract_from_document(document)
    except LLMUnavailableError as exc:
        return _skip_if_unavailable(exc)

    values = _values(result)
    assert values.get("employee.dni") == "30123456"
    assert values.get("employee.fecha_nacimiento") == "1995-03-15"
    assert result.warnings == []


def test_pdf_with_text_extraction(service: ExtractionService) -> None:
    lines = [
        "CONTRATO DE TRABAJO - Por tiempo indeterminado",
        "Empleador: HumanIA S.A., CUIT 30-71234567-1, con domicilio en Av. Ejemplo 1234, Cordoba",
        "Empleado: Maria Gomez, DNI 28.456.789, nacida el 02/11/1990",
        "Puesto: Analista de Datos. Inicio: 01/02/2027",
        "Jornada: Lunes a viernes de 9:00 a 17:00 hs",
        "Remuneracion mensual bruta: $ 1.800.000,50",
    ]
    pdf = pymupdf.open()
    page = pdf.new_page()
    for index, line in enumerate(lines):
        page.insert_text((40, 60 + index * 24), line, fontsize=10)
    document = DocumentLoader().load(bytes(pdf.tobytes()), "contrato.pdf")
    assert document.text and not document.images

    try:
        result = service.extract_from_document(document)
    except LLMUnavailableError as exc:
        return _skip_if_unavailable(exc)

    values = _values(result)
    assert values.get("company.cuit") == "30712345671"
    assert values.get("employee.dni") == "28456789"
    assert values.get("employee.fecha_nacimiento") == "1990-11-02"
    assert values.get("terms.fecha_inicio") == "2027-02-01"
    assert values.get("terms.remuneracion_bruta") == "1800000.50"
