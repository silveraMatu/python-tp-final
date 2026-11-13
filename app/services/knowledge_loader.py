"""Carga y troceo de las fuentes de conocimiento del RAG.

Fuentes: las cláusulas aprobadas (``STATIC_CLAUSES``) y los documentos PDF/MD/TXT
de la carpeta de conocimiento. Solo se lee: nada de lo indexado puede modificar
una cláusula ni el estado del contrato.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Final, Iterable, List, Sequence, Union

import pymupdf

from app.services.template_service import STATIC_CLAUSES

KNOWLEDGE_EXTENSIONS: Final[frozenset[str]] = frozenset({".pdf", ".md", ".txt"})
_JINJA_TAG_RE: Final[re.Pattern[str]] = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")

MetadataValue = Union[str, int]


@dataclass(frozen=True)
class Chunk:
    """Fragmento indexable con su origen."""

    id: str
    text: str
    source: str
    kind: str  # "clause" | "document"
    metadata: Dict[str, MetadataValue] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadReport:
    """Resultado de cargar la carpeta de conocimiento."""

    chunks: List[Chunk] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def make_chunk_id(source: str, index: int, text: str) -> str:
    """Id determinista: reindexar el mismo contenido produce los mismos ids."""
    return hashlib.sha256(f"{source}|{index}|{text}".encode("utf-8")).hexdigest()[:32]


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> List[str]:
    """Trocea por párrafos hasta ``max_chars``; los párrafos enormes se parten con solape."""
    if max_chars <= 0 or not 0 <= overlap < max_chars:
        raise ValueError("max_chars debe ser > 0 y 0 <= overlap < max_chars")

    paragraphs = [" ".join(p.split()) for p in _PARAGRAPH_SPLIT_RE.split(text)]
    chunks: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for paragraph in filter(None, paragraphs):
        if len(paragraph) > max_chars:
            flush()
            chunks.extend(_split_long(paragraph, max_chars, overlap))
        elif current and len(current) + 1 + len(paragraph) > max_chars:
            flush()
            current = paragraph
        else:
            current = f"{current}\n{paragraph}" if current else paragraph
    flush()
    return chunks


def _split_long(paragraph: str, max_chars: int, overlap: int) -> List[str]:
    pieces: List[str] = []
    start = 0
    while start < len(paragraph):
        end = min(start + max_chars, len(paragraph))
        if end < len(paragraph):
            space = paragraph.rfind(" ", start + max_chars // 2, end)
            end = space if space != -1 else end
        pieces.append(paragraph[start:end].strip())
        if end >= len(paragraph):
            break
        # El solape arranca en un límite de palabra para no cortar palabras a la mitad.
        start = max(end - overlap, start + 1)
        if paragraph[start - 1] != " ":
            next_space = paragraph.find(" ", start, end)
            start = next_space + 1 if next_space != -1 else end
    return [piece for piece in pieces if piece]


def clause_chunks() -> List[Chunk]:
    """Un fragmento por cláusula aprobada; los marcadores Jinja se muestran como ``[campo]``."""
    chunks: List[Chunk] = []
    for clause in STATIC_CLAUSES:
        body = _JINJA_TAG_RE.sub(r"[\1]", clause.body)
        text = f"{clause.heading}\n{body}"
        source = f"clausula:{clause.ordinal}"
        chunks.append(
            Chunk(
                id=make_chunk_id(source, 0, text),
                text=text,
                source=source,
                kind="clause",
                metadata={"ordinal": clause.ordinal, "title": clause.title},
            )
        )
    return chunks


def file_chunks(path: Path, max_chars: int = 800, overlap: int = 100) -> List[Chunk]:
    """Fragmentos de un PDF (por página), MD o TXT.

    Raises:
        ValueError: extensión no soportada o archivo sin texto extraíble.
    """
    extension = path.suffix.lower()
    if extension not in KNOWLEDGE_EXTENSIONS:
        raise ValueError(f"Tipo no soportado para el conocimiento: {path.name}")

    pages: List[tuple[int, str]]
    if extension == ".pdf":
        with pymupdf.open(str(path)) as document:
            pages = [(index + 1, page.get_text()) for index, page in enumerate(document)]
    else:
        pages = [(0, path.read_text(encoding="utf-8", errors="replace"))]

    chunks: List[Chunk] = []
    counter = 0
    for page_number, text in pages:
        for piece in chunk_text(text, max_chars, overlap):
            metadata: Dict[str, MetadataValue] = {"chunk": counter}
            if page_number:
                metadata["page"] = page_number
            chunks.append(
                Chunk(
                    id=make_chunk_id(path.name, counter, piece),
                    text=piece,
                    source=path.name,
                    kind="document",
                    metadata=metadata,
                )
            )
            counter += 1
    if not chunks:
        raise ValueError(f"{path.name} no tiene texto extraíble (¿PDF escaneado?)")
    return chunks


def load_knowledge_dir(directory: Path, max_chars: int = 800, overlap: int = 100) -> LoadReport:
    """Carga todos los documentos soportados de ``directory`` (si existe)."""
    report = LoadReport()
    if not directory.is_dir():
        return report
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in KNOWLEDGE_EXTENSIONS:
            report.skipped.append(f"{path.name}: tipo no soportado")
            continue
        try:
            report.chunks.extend(file_chunks(path, max_chars, overlap))
            report.sources.append(path.name)
        except Exception as exc:  # un archivo roto no debe frenar el resto
            report.skipped.append(f"{path.name}: {exc}")
    return report


def seed_knowledge(sources: Iterable[Path], directory: Path) -> List[Path]:
    """Copia archivos a la carpeta de conocimiento (sin pisar los existentes)."""
    directory.mkdir(parents=True, exist_ok=True)
    copied: List[Path] = []
    for source in sources:
        target = directory / source.name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
            copied.append(target)
    return copied


def describe(chunks: Sequence[Chunk]) -> str:
    """Resumen corto para logs/CLI."""
    kinds = sorted({chunk.kind for chunk in chunks})
    return f"{len(chunks)} fragmentos ({', '.join(kinds) or 'vacío'})"
