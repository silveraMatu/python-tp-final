"""Utilidades compartidas por los tests."""

from __future__ import annotations

import math
import re
from pathlib import Path
import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import pymupdf
from docx import Document

from app.core.exceptions import PdfConversionError
from app.services.rag_service import RagAnswer, SearchHit

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


class ScriptedLLM:
    """LLM falso: responde según el tipo de llamada (por el prompt de sistema)."""

    KINDS = {
        "clasificador de intención": "intent",
        "extractor de datos": "extraction",
        "Respondes consultas": "rag",
    }

    def __init__(self) -> None:
        self.queues: Dict[str, List[str]] = {"intent": [], "extraction": [], "rag": []}
        self.calls: List[str] = []

    def push(self, kind: str, *responses: str) -> None:
        self.queues[kind].extend(responses)

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        images: Sequence[bytes] = (),
    ) -> str:
        kind = next(name for text, name in self.KINDS.items() if text in system)
        self.calls.append(kind)
        assert self.queues[kind], f"llamada inesperada al LLM ({kind})"
        return self.queues[kind].pop(0)

    def count(self, kind: str) -> int:
        return self.calls.count(kind)


def intent_json(intent: str, decision: str | None = None) -> str:
    return json.dumps({"intent": intent, "decision": decision})


def extraction_json(*fields: tuple[str, str, str, float]) -> str:
    return json.dumps(
        {
            "fields": [
                {"field_name": p, "value": v, "evidence": e, "confidence": c}
                for p, v, e, c in fields
            ]
        }
    )


class FakeRag:
    def __init__(self) -> None:
        self.questions: List[str] = []

    def answer(self, question: str) -> RagAnswer:
        self.questions.append(question)
        hit = SearchHit("id", "texto", "clausula:SEXTA", "clause", 0.9)
        return RagAnswer("La cláusula SEXTA exige confidencialidad.", True, [hit])


