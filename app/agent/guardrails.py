"""Guardrails deterministas del agente (se evalúan antes que el LLM).

El agente no tiene ninguna ruta de código para aprobar, firmar ni modificar
cláusulas; estos filtros solo existen para responder con claridad cuando alguien
lo pide, sin gastar una llamada al modelo.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Final, Tuple

MAX_MESSAGE_CHARS: Final[int] = 4_000

REFUSAL_APPROVAL: Final[str] = (
    "No puedo aprobar, firmar ni formalizar contratos: esa decisión es de un responsable "
    "autorizado. Cuando los datos estén completos puedo enviar el borrador a revisión humana."
)
REFUSAL_CLAUSES: Final[str] = (
    "No puedo redactar ni modificar cláusulas: el texto legal del contrato es el aprobado por "
    "la empresa y solo se completan los datos. Si necesitás un cambio en las cláusulas, debe "
    "hacerlo el área legal sobre la plantilla."
)


class GuardVerdict(str, Enum):
    """Resultado del filtro de entrada."""

    OK = "OK"
    REFUSE_APPROVAL = "REFUSE_APPROVAL"
    REFUSE_CLAUSE_EDIT = "REFUSE_CLAUSE_EDIT"


def normalize_text(text: str) -> str:
    """Minúsculas, sin tildes y con espacios colapsados (para comparar patrones)."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(stripped.lower().split())


_APPROVAL_VERBS: Final[str] = r"(?:aprueba|aprobar|aproba|firma|firmar|formaliza|formalizar)"
# Un verbo al inicio ("aprobá", "formalizalo") es una orden inequívoca.
_APPROVAL_COMMAND: Final[re.Pattern[str]] = re.compile(
    rf"^\W*(?:por favor[,\s]+)?(?:(?:podes|puedes|podrias)\s+)?{_APPROVAL_VERBS}(?:lo|la)?\b"
)
# Dentro de la frase solo cuenta si no es una pregunta ("¿quién firma el contrato?").
_APPROVAL_IN_SENTENCE: Final[Tuple[re.Pattern[str], ...]] = (
    re.compile(
        rf"\b{_APPROVAL_VERBS}(?:lo|la)?\s+(?:el|este|ese|al|nuestro)\s+(?:contrato|documento)\b"
    ),
    re.compile(r"\b(?:da|dar|dalo|damelo)\s+(?:por\s+)?aprobad[oa]\b"),
    re.compile(r"\bmarca(?:lo|r)?\s+(?:\w+\s+){0,3}como\s+aprobad[oa]\b"),
)
_QUESTION_START: Final[re.Pattern[str]] = re.compile(
    r"^\W*(?:quien|quienes|cuando|como|donde|cual|cuales|que|por que|para que)\b"
)
_CLAUSE_EDIT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:modific|cambi|agreg|anad|redact|escrib|elimin|quit|borr|reemplaz|inventa|reform|"
    r"edit|actualiz)\w*\b[^.?!\n]{0,40}\bclausulas?\b"
)


def check_message(message: str) -> GuardVerdict:
    """Detecta pedidos que el agente nunca debe ejecutar."""
    text = normalize_text(message)
    if _APPROVAL_COMMAND.search(text):
        return GuardVerdict.REFUSE_APPROVAL
    if not _QUESTION_START.match(text) and any(
        pattern.search(text) for pattern in _APPROVAL_IN_SENTENCE
    ):
        return GuardVerdict.REFUSE_APPROVAL
    if _CLAUSE_EDIT_PATTERN.search(text):
        return GuardVerdict.REFUSE_CLAUSE_EDIT
    return GuardVerdict.OK


def truncate(message: str) -> str:
    """Limita el largo del mensaje que se envía al modelo."""
    return message.strip()[:MAX_MESSAGE_CHARS]
