"""Normalización y neutralización de texto no confiable (mensajes, documentos)."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_KEEP_CONTROLS: Final[frozenset[str]] = frozenset({"\n", "\t"})
_REPEATED_CHAR_RE: Final[re.Pattern[str]] = re.compile(r"(.)\1{29,}", re.DOTALL)
_BLANK_LINES_RE: Final[re.Pattern[str]] = re.compile(r"\n{4,}")
_SPACES_RE: Final[re.Pattern[str]] = re.compile(r"[ \t\u00a0]{2,}")
# Marcas de plantillas de chat y delimitadores propios que un usuario podría intentar falsificar.
_TEMPLATE_TOKENS_RE: Final[re.Pattern[str]] = re.compile(
    r"<\|[^|>]{1,30}\|>|\[/?(?:INST|SYS)\]|</?s>|<</?SYS>>", re.IGNORECASE
)
_LEET: Final[dict[int, str]] = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)


def normalize_input(text: str) -> str:
    """Deja el texto en una forma segura y predecible.

    - NFKC (unifica variantes tipográficas y de ancho completo).
    - Elimina caracteres invisibles o de control (ancho cero, direccionales, etc.), que se
      usan para esconder instrucciones o falsear lo que ve el revisor.
    - Colapsa espacios, saltos de línea y repeticiones absurdas (inundación).
    """
    normalized = unicodedata.normalize("NFKC", text)
    kept = []
    for char in normalized:
        category = unicodedata.category(char)
        if category in ("Cf", "Co", "Cs", "Cn") or (category == "Cc" and char not in _KEEP_CONTROLS):
            continue
        kept.append(char)
    cleaned = "".join(kept).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _REPEATED_CHAR_RE.sub(lambda m: m.group(1) * 5, cleaned)
    cleaned = _SPACES_RE.sub(" ", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n\n", cleaned)
    return cleaned.strip()


def neutralize_delimiters(text: str) -> str:
    """Quita lo que permitiría cerrar el bloque de datos de un prompt o imitar su formato."""
    text = _TEMPLATE_TOKENS_RE.sub("[filtrado]", text)
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def strip_accents(text: str) -> str:
    """Sin tildes ni diacríticos."""
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


def fold(text: str, leet: bool = True) -> str:
    """Forma comparable: sin tildes, en minúsculas, con 'leetspeak' y separadores colapsados.

    Sirve para detectar evasiones como ``1gn0ra``, ``i.g.n.o.r.a`` o ``IGNORÁ``. Con
    ``leet=False`` los dígitos se conservan (necesario para detectar cantidades).
    """
    lowered = strip_accents(text).lower()
    if leet:
        lowered = lowered.translate(_LEET)
    # "i g n o r a" / "i.g.n.o.r.a" -> "ignora" (cuatro o más letras sueltas seguidas)
    lowered = re.sub(
        r"\b(?:[a-z][ .\-_*]){3,}[a-z]\b",
        lambda m: re.sub(r"[ .\-_*]", "", m.group(0)),
        lowered,
    )
    return " ".join(lowered.split())
