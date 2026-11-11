from __future__ import annotations

import pymupdf
import pytest

from app.core.exceptions import UnsupportedDocumentError
from app.services.document_loader import DocumentLoader


def make_pdf(pages: list[str]) -> bytes:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = bytes(document.tobytes())
    document.close()
    return data


def make_png(width: int = 2000, height: int = 1000) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.clear_with(255)
    return bytes(pixmap.tobytes("png"))


def png_size(data: bytes) -> tuple[int, int]:
    pixmap = pymupdf.Pixmap(data)
    return pixmap.width, pixmap.height


def test_pdf_with_text_layer_uses_text() -> None:
    text = "CONTRATO DE TRABAJO entre HumanIA S.A. y Juan Pérez, DNI 30.123.456"
    loaded = DocumentLoader().load(make_pdf([text]), "contrato.pdf")
    assert "DNI 30.123.456" in loaded.text
    assert loaded.images == ()


def test_scanned_pdf_pages_are_rasterized_and_resized() -> None:
    loaded = DocumentLoader(max_image_side=800).load(make_pdf(["", "x"]), "scan.pdf")
    assert loaded.text == "" and len(loaded.images) == 2
    assert max(png_size(loaded.images[0])) <= 801


def test_pdf_page_limit() -> None:
    long_text = "texto de relleno suficientemente largo para superar el mínimo " * 2
    loaded = DocumentLoader(max_pages=2).load(make_pdf([long_text] * 5), "x.pdf")
    assert loaded.text.count("relleno") == 4  # 2 páginas x 2 repeticiones


def test_image_is_normalized_to_png_with_max_side() -> None:
    loaded = DocumentLoader(max_image_side=640).load(make_png(), "dni.png")
    assert loaded.text == "" and len(loaded.images) == 1
    assert max(png_size(loaded.images[0])) == 640


@pytest.mark.parametrize(
    ("data", "name", "message"),
    [
        (b"hola", "notas.txt", "no soportado"),
        (b"", "a.pdf", "vacío"),
        (b"no soy pdf", "a.pdf", "no es un PDF"),
        (b"%PDF-1.4 roto", "a.pdf", "No se pudo leer"),
        (b"no soy una imagen", "a.png", "No se pudo leer"),
    ],
)
def test_invalid_files(data: bytes, name: str, message: str) -> None:
    with pytest.raises(UnsupportedDocumentError, match=message):
        DocumentLoader().load(data, name)


def test_size_limit() -> None:
    with pytest.raises(UnsupportedDocumentError, match="máximo"):
        DocumentLoader(max_bytes=10).load(b"%PDF" + b"x" * 20, "a.pdf")
