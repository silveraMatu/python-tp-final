"""Carga de documentos subidos (PDF e imágenes) para su extracción."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, List, Tuple

import pymupdf

from app.core.exceptions import UnsupportedDocumentError

IMAGE_EXTENSIONS: Final[frozenset[str]] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
PDF_EXTENSION: Final[str] = ".pdf"
_MAX_TEXT_CHARS: Final[int] = 12_000


@dataclass(frozen=True)
class LoadedDocument:
    """Contenido listo para el extractor: texto (si lo hay) e imágenes PNG."""

    filename: str
    text: str = ""
    images: Tuple[bytes, ...] = ()


class DocumentLoader:
    """Valida y convierte PDFs/imágenes.

    - PDF con capa de texto: se usa el texto.
    - PDF escaneado (poco texto) o imagen: se rasteriza a PNG reducido para el modelo de visión.
    """

    def __init__(
        self,
        max_bytes: int = 15 * 1024 * 1024,
        max_pages: int = 3,
        max_image_side: int = 1280,
        min_text_chars: int = 40,
    ) -> None:
        self._max_bytes = max_bytes
        self._max_pages = max_pages
        self._max_side = max_image_side
        self._min_text_chars = min_text_chars

    def load(self, data: bytes, filename: str) -> LoadedDocument:
        """Lee el archivo.

        Raises:
            UnsupportedDocumentError: tipo no soportado, vacío, demasiado grande o corrupto.
        """
        extension = Path(filename).suffix.lower()
        if extension != PDF_EXTENSION and extension not in IMAGE_EXTENSIONS:
            raise UnsupportedDocumentError(
                f"Tipo de archivo no soportado: '{extension or filename}'. "
                "Se admiten PDF, PNG, JPG y WEBP."
            )
        if not data:
            raise UnsupportedDocumentError("El archivo está vacío")
        if len(data) > self._max_bytes:
            raise UnsupportedDocumentError(
                f"El archivo supera el máximo de {self._max_bytes // (1024 * 1024)} MB"
            )
        if extension == PDF_EXTENSION and not data.lstrip().startswith(b"%PDF"):
            raise UnsupportedDocumentError("El archivo no es un PDF válido")

        try:
            with pymupdf.open(stream=data, filetype=extension.lstrip(".")) as document:
                if document.page_count == 0:
                    raise UnsupportedDocumentError("El documento no tiene páginas")
                if extension == PDF_EXTENSION:
                    return self._load_pdf(document, filename)
                return LoadedDocument(filename, images=(self._render(document[0]),))
        except UnsupportedDocumentError:
            raise
        except Exception as exc:
            raise UnsupportedDocumentError(f"No se pudo leer '{filename}': {exc}") from exc

    def _load_pdf(self, document: pymupdf.Document, filename: str) -> LoadedDocument:
        texts: List[str] = []
        images: List[bytes] = []
        for index in range(min(document.page_count, self._max_pages)):
            page = document[index]
            page_text = page.get_text().strip()
            if len(page_text) >= self._min_text_chars:
                texts.append(page_text)
            else:
                images.append(self._render(page))
        return LoadedDocument(
            filename, text="\n\n".join(texts)[:_MAX_TEXT_CHARS], images=tuple(images)
        )

    def _render(self, page: pymupdf.Page) -> bytes:
        """PNG con el lado mayor limitado a ``max_image_side`` (acelera la inferencia en CPU)."""
        zoom = self._max_side / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return bytes(pixmap.tobytes("png"))
