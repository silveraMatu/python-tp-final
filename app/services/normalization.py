"""Normalización determinista de valores extraídos al formato que espera el esquema.

Si un valor no se puede normalizar, se devuelve tal cual: la validación del
esquema lo rechazará y el usuario será consultado. Nunca se "adivina".
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Final

_MONTHS: Final[dict[str, int]] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}  # fmt: skip
_NUMERIC_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
_ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_TEXT_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de(?:l)?\s+(\d{4})$", re.IGNORECASE
)
_THOUSANDS_DOT_RE: Final[re.Pattern[str]] = re.compile(r"^\d{1,3}(\.\d{3})+$")
_DECIMAL_COMMA_RE: Final[re.Pattern[str]] = re.compile(r"^\d+,\d{1,2}$")

_DATE_FIELDS: Final[frozenset[str]] = frozenset({"fecha_nacimiento", "fecha_inicio"})


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )


def _to_iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_date(raw: str) -> str:
    """``15/03/1995`` o ``15 de marzo de 1995`` -> ``1995-03-15``."""
    text = raw.strip()
    if match := _ISO_DATE_RE.match(text):
        year, month, day = (int(g) for g in match.groups())
        return _to_iso(year, month, day) or raw
    if match := _NUMERIC_DATE_RE.match(text):
        day, month, year = (int(g) for g in match.groups())
        return _to_iso(year, month, day) or raw
    if match := _TEXT_DATE_RE.match(text):
        month = _MONTHS.get(_strip_accents(match.group(2).lower()))
        if month is not None:
            return _to_iso(int(match.group(3)), month, int(match.group(1))) or raw
    return raw


def normalize_amount(raw: str) -> str:
    """``$ 2.500.000,50`` -> ``2500000.50`` (formato es-AR)."""
    text = re.sub(r"(?i)\b(ars|pesos?|argentinos?)\b|\$", "", raw).strip().replace(" ", "")
    if not re.fullmatch(r"[\d.,]+", text):
        return raw
    if "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".") if _DECIMAL_COMMA_RE.match(text) else text.replace(",", "")
    elif "." in text and _THOUSANDS_DOT_RE.match(text):
        text = text.replace(".", "")
    return text if re.fullmatch(r"\d+(\.\d+)?", text) else raw


def normalize_modality(raw: str) -> str:
    """Etiqueta en español -> valor de ``EmploymentType``."""
    text = _strip_accents(raw).casefold()
    if raw.strip().upper() in {"INDETERMINATE", "FIXED_TERM", "TRIAL_PERIOD", "PART_TIME"}:
        return raw.strip().upper()
    if "indetermin" in text:
        return "INDETERMINATE"
    if "plazo fijo" in text or "determinado" in text:
        return "FIXED_TERM"
    if "prueba" in text:
        return "TRIAL_PERIOD"
    if "parcial" in text or "part time" in text or "part-time" in text:
        return "PART_TIME"
    return raw


def normalize_value(field_path: str, raw: str) -> str:
    """Normaliza ``raw`` según el campo destino (``"employee.dni"``, ...)."""
    name = field_path.split(".", 1)[-1]
    value = " ".join(raw.split())
    if name in _DATE_FIELDS:
        return normalize_date(value)
    if name == "remuneracion_bruta":
        return normalize_amount(value)
    if name == "modalidad":
        return normalize_modality(value)
    if name == "dni":
        digits = re.sub(r"\D", "", value)
        return digits if 7 <= len(digits) <= 8 else value
    if name in {"cuil", "cuit"}:
        digits = re.sub(r"\D", "", value)
        return digits if len(digits) == 11 else value
    return value
