"""Utilidades PyMuPDF para los PDF generados: texto, verificación, marca y metadatos."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final, List, Optional, Sequence, Union

import pymupdf

# Los encabezados y pies viven dentro de los márgenes de la página (2,54 cm por defecto);
# el cuerpo se lee recortando esas franjas para que no se intercalen con las cláusulas
# que cruzan de página.
BODY_MARGIN_PT: Final[float] = 66.0
_VERIFICATION_RE: Final[re.Pattern[str]] = re.compile(
    r"Código de verificación:\s*([0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4})"
)

PdfSource = Union[bytes, Path]


def _open(source: PdfSource) -> pymupdf.Document:
    if isinstance(source, Path):
        return pymupdf.open(str(source))
    return pymupdf.open(stream=source, filetype="pdf")


def normalize_whitespace(text: str) -> str:
    """Colapsa espacios y saltos de línea (y quita guiones blandos)."""
    return " ".join(text.replace("\u00ad", "").split())


def extract_body_text(source: PdfSource) -> str:
    """Texto del cuerpo de todas las páginas, sin encabezados ni pies."""
    with _open(source) as document:
        chunks: List[str] = []
        for page in document:
            clip = pymupdf.Rect(
                0, BODY_MARGIN_PT, page.rect.width, page.rect.height - BODY_MARGIN_PT
            )
            chunks.append(page.get_text("text", clip=clip))
        return "\n".join(chunks)


def extract_full_text(source: PdfSource) -> str:
    """Texto completo (incluye encabezados y pies)."""
    with _open(source) as document:
        return "\n".join(page.get_text("text") for page in document)


def find_verification_code(source: PdfSource) -> Optional[str]:
    """Código de verificación impreso en el pie, si existe."""
    match = _VERIFICATION_RE.search(normalize_whitespace(extract_full_text(source)))
    return match.group(1) if match else None


def clause_violations(body_text: str, expected: Sequence[tuple[str, str]]) -> List[str]:
    """Cláusulas (encabezado + cuerpo) que no aparecen tal cual en el texto del PDF."""
    haystack = normalize_whitespace(body_text)
    return [
        f"la cláusula '{heading}' no figura íntegra en el PDF"
        for heading, body in expected
        if normalize_whitespace(f"{heading} {body}") not in haystack
    ]


def apply_watermark(path: Path, text: str = "BORRADOR") -> None:
    """Marca de agua diagonal semitransparente en cada página (reemplaza el archivo)."""
    with _editing(path) as document:
        for page in document:
            center = pymupdf.Point(page.rect.width / 2, page.rect.height / 2)
            fontsize = min(page.rect.width, page.rect.height) / 4.5
            width = pymupdf.get_text_length(text, fontname="helv", fontsize=fontsize)
            origin = pymupdf.Point(center.x - width / 2, center.y + fontsize / 3)
            page.insert_text(
                origin,
                text,
                fontsize=fontsize,
                fontname="helv",
                color=(0.55, 0.55, 0.55),
                fill_opacity=0.22,
                morph=(center, pymupdf.Matrix(45)),
                overlay=True,
            )


def set_metadata(path: Path, title: str, subject: str, keywords: str, author: str) -> None:
    """Metadatos del PDF (título, ID del contrato, estado y código)."""
    with _editing(path) as document:
        document.set_metadata(
            {
                "title": title,
                "subject": subject,
                "keywords": keywords,
                "author": author,
                "creator": "HumanIA Contratos",
                "producer": "HumanIA Contratos",
            }
        )


@contextmanager
def _editing(path: Path) -> Iterator[pymupdf.Document]:
    """Abre ``path`` para modificarlo y lo reemplaza de forma atómica al terminar bien."""
    handle, temp_name = tempfile.mkstemp(suffix=".pdf", dir=str(path.parent))
    os.close(handle)
    try:
        with pymupdf.open(str(path)) as document:
            yield document
            document.save(temp_name, garbage=3, deflate=True)
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
