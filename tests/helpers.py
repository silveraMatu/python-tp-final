"""Utilidades compartidas por los tests."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Optional

import pymupdf
from docx import Document

from app.core.exceptions import PdfConversionError

_CODE_RE = re.compile(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}")
# La fuente base de PyMuPDF solo dibuja Latin-1; esta, embebida, soporta "–" y las comillas “ ”.
_FONT = "uni"
_FONT_BUFFER = pymupdf.Font("helv").buffer


class FakePdfConverter:
    """Convierte un DOCX en un PDF simple con PyMuPDF (sin LibreOffice).

    Dibuja encabezado, párrafos de cuerpo y pie en las mismas franjas que el PDF real,
    y permite simular alteraciones o fallos.
    """

    def __init__(
        self,
        tamper: Optional[Callable[[str], str]] = None,
        wrong_code: Optional[str] = None,
        fail: bool = False,
    ) -> None:
        self.tamper = tamper
        self.wrong_code = wrong_code
        self.fail = fail
        self.calls = 0

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        self.calls += 1
        if self.fail:
            raise PdfConversionError("conversión simulada fallida")

        document = Document(str(docx_path))
        section = document.sections[0]
        header = " ".join(p.text for p in section.header.paragraphs).strip()
        footer = " ".join(p.text for p in section.footer.paragraphs).strip() + " 1"
        if self.wrong_code:
            footer = _CODE_RE.sub(self.wrong_code, footer)
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        if self.tamper:
            paragraphs = [self.tamper(text) for text in paragraphs]

        pdf = pymupdf.open()
        page = self._new_page(pdf, header, footer)
        y = 80.0
        for text in paragraphs:
            lines = max(1, math.ceil(len(text) * 4.9 / 451))
            height = lines * 11.5 + 6
            if y + height > 765:
                page = self._new_page(pdf, header, footer)
                y = 80.0
            # insert_textbox no dibuja nada si el texto no entra: se agranda hasta que entre.
            rect = pymupdf.Rect(72, y, 523, y + height)
            while page.insert_textbox(rect, text, fontsize=9, fontname=_FONT) < 0:
                height += 11.5
                rect = pymupdf.Rect(72, y, 523, y + height)
            y += height
        target = output_dir / f"{docx_path.stem}.pdf"
        pdf.save(str(target))
        pdf.close()
        return target

    @staticmethod
    def _new_page(pdf: pymupdf.Document, header: str, footer: str) -> pymupdf.Page:
        page = pdf.new_page(width=595, height=842)
        page.insert_font(fontname=_FONT, fontbuffer=_FONT_BUFFER)
        if header:
            page.insert_text((72, 45), header, fontsize=9, fontname=_FONT)
        page.insert_text((72, 800), footer, fontsize=8, fontname=_FONT)
        return page
