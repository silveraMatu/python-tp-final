"""Detección de intentos de inyección de prompt y de abuso en texto no confiable.

Se aplica a los mensajes del usuario y, como defensa contra la inyección *indirecta*, al
texto extraído de documentos y a lo que devuelve el modelo. Es deliberadamente estricto:
ante una coincidencia se rechaza el contenido en lugar de intentar "limpiarlo".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Final, List, Tuple

from app.security.text import fold


class Threat(str, Enum):
    """Categorías de amenaza (los nombres se registran; el usuario no los ve)."""

    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    ROLE_HIJACK = "ROLE_HIJACK"
    PROMPT_EXTRACTION = "PROMPT_EXTRACTION"
    SECRET_EXFILTRATION = "SECRET_EXFILTRATION"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    JAILBREAK = "JAILBREAK"
    DELIMITER_ESCAPE = "DELIMITER_ESCAPE"
    ENCODED_PAYLOAD = "ENCODED_PAYLOAD"
    OUTPUT_FLOODING = "OUTPUT_FLOODING"
    MARKUP_INJECTION = "MARKUP_INJECTION"
    CODE_INJECTION = "CODE_INJECTION"


@dataclass(frozen=True)
class ScanResult:
    """Resultado de analizar un texto."""

    threats: Tuple[Threat, ...] = ()

    @property
    def blocked(self) -> bool:
        return bool(self.threats)

    def label(self) -> str:
        """Categorías separadas por coma (para la auditoría)."""
        return ",".join(t.value for t in self.threats)


_VERBS_SHOW = (
    r"(?:muestra\w*|mostra\w*|muestr\w*|revela\w*|repite\w*|repeti\w*|imprim\w*|dime|decime|"
    r"dame|dameme|copia\w*|pega\w*|escribe\w*|escribi\w*|lista\w*|devuelve\w*|devolve\w*|"
    r"filtra\w*|exporta\w*|envia\w*|print|show|reveal|repeat|output|display|tell|give|leak|"
    r"dump|list|send|expose)"
)

# Patrones sobre texto "plegado" (sin tildes, minúsculas, leetspeak resuelto).
_FOLDED_PATTERNS: Final[Dict[Threat, List[re.Pattern[str]]]] = {
    Threat.INSTRUCTION_OVERRIDE: [
        re.compile(
            r"\b(?:ignor\w*|olvid\w*|descart\w*|omit\w*|saltea\w*|anul\w*|desobede\w*|"
            r"deja\w* de (?:seguir|obedecer))\b.{0,50}\b(?:instruccion\w*|regla\w*|indicacion\w*|"
            r"restriccion\w*|directriz\w*|directrices|prompt|anterior\w*|previ\w*|todo|"
            r"lo que te (?:dijeron|dije)|programacion)\b"
        ),
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|skip|drop)\b.{0,50}\b(?:previous|"
            r"prior|above|all|any|instructions?|rules?|guidelines?|system|safety|polic\w+)\b"
        ),
        re.compile(
            r"\b(?:a partir de ahora|desde ahora|de ahora en (?:mas|adelante)|from now on)\b.{0,60}"
            r"\b(?:debes|tienes que|vas a|obedece\w*|responde\w*|you (?:must|will|are)|only)\b"
        ),
        re.compile(r"\b(?:nuevas? instruccion\w*|new instructions?|updated instructions?)\b"),
    ],
    Threat.ROLE_HIJACK: [
        re.compile(
            r"\b(?:ahora eres|eres ahora|ahora sos|finge\w* (?:ser|que)|simula\w* (?:ser|que)|"
            r"pretend (?:to be|you)|you are now|roleplay|role-play|imagina que (?:eres|sos))\b"
        ),
        re.compile(
            r"\b(?:actua(?:s)?|comportate|act) como (?:un |una |el |la |si fueras )?(?:asistente|ia|ai|"
            r"bot|chatbot|hacker|administrador|admin|root|sistema|modelo|dan|desarrollador|"
            r"developer|programador|revisor|aprobador|jefe|gerente|abogado|juez|terminal|shell|"
            r"linux|assistant|system)\b|\bact as (?:an? |the )?(?:assistant|ai|bot|hacker|admin|"
            r"root|system|developer|reviewer|approver|terminal|shell|linux)\b"
        ),
        re.compile(r"(?m)^\s*(?:system|sistema|assistant|asistente|developer|desarrollador|root)\s*[:>\]]"),
        re.compile(r"<\|?\s*(?:im_start|im_end|system|assistant|user|endoftext)\s*\|?>"),
        re.compile(r"\[/?(?:inst|sys|system)\]|###\s*(?:instruction|system|instruccion)"),
    ],
    Threat.PROMPT_EXTRACTION: [
        re.compile(
            rf"\b{_VERBS_SHOW}\b.{{0,60}}\b(?:prompt|system prompt|instruccion\w* (?:internas?|"
            r"del sistema|iniciales|originales|ocultas?|que te dieron)|reglas internas|"
            r"mensaje del sistema|your (?:initial |system |hidden )?instructions|"
            r"hidden instructions|configuracion (?:interna|del sistema)|como estas programad\w+)\b"
        ),
        re.compile(
            r"\b(?:cuales? son tus (?:instruccion\w*|reglas)|what (?:are|were) your "
            r"(?:instructions|rules)|como (?:funciona|estas configurad\w+) (?:por dentro|internamente))\b"
        ),
        re.compile(
            r"\b(?:todo lo (?:anterior|de arriba)|everything above|texto anterior|"
            r"lo que (?:esta|hay) (?:arriba|antes)|first (?:message|words))\b"
        ),
        re.compile(r"\b(?:system ?prompt|prompt (?:del )?sistema|prompt original)\b"),
    ],
    Threat.SECRET_EXFILTRATION: [
        re.compile(
            rf"\b{_VERBS_SHOW}\b.{{0,50}}\b(?:api ?key\w*|apikey|x-api-key|token\w*|clave\w*|"
            r"contrasena\w*|password\w*|secret\w*|credencial\w*|variables? de entorno|"
            r"environment|ruta\w* (?:del|de) (?:servidor|archivo|base)|base de datos|"
            r"hash\w* de (?:la )?(?:key|clave))\b"
        ),
        re.compile(
            r"\b(?:cual es|que es|dame|dime|what is) (?:tu|la|el|your)? ?(?:api ?key|clave|"
            r"password|contrasena|token|secret\w*)\b"
        ),
        re.compile(r"\bhumania_[a-z_]+\b|\bkey_sha256\b|\.env\b|\bhk_[a-z0-9_\-]{8,}"),
        re.compile(r"(?:/etc/passwd|/etc/shadow|/home/|c:\\\\|\.sqlite\b|contracts\.db|\bchroma\b)"),
    ],
    Threat.DATA_EXFILTRATION: [
        re.compile(
            r"\b(?:contratos?|datos|dni|cuil|cuit|informacion|historial|chat|conversacion\w*|"
            r"documentos?|domicilios?)\b.{0,40}\b(?:de otros?|de otras? personas?|de los demas|"
            r"de otro usuario|de todos|de cada (?:empleado|usuario|persona)|ajenos?|de (?:los|las) "
            r"(?:otros|otras|demas)|de terceros)\b"
        ),
        re.compile(
            rf"\b(?:{_VERBS_SHOW}|todos los)\b.{{0,30}}\b(?:todos los )?(?:contratos|usuarios|"
            r"empleados|dnis?|cuils?|keys|claves|conversaciones|historiales)\b"
        ),
        re.compile(r"\b(?:base de datos completa|dump(?:ea)?|exporta\w* todo|volcado)\b"),
    ],
    Threat.JAILBREAK: [
        re.compile(
            r"\b(?:dan|do anything now|modo desarrollador|developer mode|modo dios|god mode|"
            r"sin restricciones|sin filtros|sin limites|without (?:any )?restrictions|"
            r"no limitations|jailbreak\w*|unfiltered|modo sin censura|libre de reglas|"
            r"desactiva\w* (?:tus )?(?:filtros|reglas|restricciones|seguridad|guardrails?))\b"
        ),
        re.compile(
            r"\b(?:hipoteticamente|en un mundo (?:donde|sin)|for educational purposes|"
            r"con fines educativos|solo es una prueba)\b.{0,60}\b(?:ignor\w*|salt\w+|reglas|"
            r"instrucciones|rules|restrictions)\b"
        ),
    ],
    Threat.OUTPUT_FLOODING: [
        re.compile(
            r"\b(?:repite\w*|repeti\w*|escribe\w*|escribi\w*|genera\w*|imprim\w*|repeat|write|"
            r"print|generate)\b.{0,60}\b(?:\d{3,}|mil|miles|millon\w*|thousand\w*|infinit\w*|"
            r"sin parar|forever)\b.{0,20}\b(?:veces|palabras|lineas|caracteres|parrafos|times|"
            r"words|lines|characters|paragraphs)\b"
        ),
        re.compile(
            r"\b(?:respuesta|texto|contrato|documento)\b.{0,20}\b(?:extremadamente|muy|super) "
            r"(?:largo|extenso)\b|\b(?:(?:lo|el|la) )?mas (?:largo|larga|extenso|extensa) posible\b|"
            r"\bas long as possible\b|\bsin limite de (?:largo|longitud)\b"
        ),
        re.compile(
            r"\b(?:copia\w*|pega\w*|devuelve\w*|muestra\w*|mostra\w*|transcrib\w*)\b.{0,40}\b(?:"
            r"documento|archivo|contrato|texto) (?:completo|entero|integro)\b"
        ),
    ],
    Threat.MARKUP_INJECTION: [
        re.compile(r"<\s*/?\s*(?:script|iframe|img|svg|object|embed|style|link|meta|form|a)\b"),
        re.compile(r"\bjavascript\s*:|\bon(?:error|load|click|mouseover)\s*=|data\s*:\s*text/html"),
        re.compile(r"!\[[^\]]*\]\([^)]*\)|\[[^\]]+\]\(\s*(?:https?|javascript):"),
        re.compile(r"\{\{|\}\}|\{%|%\}|\$\{"),
    ],
    Threat.CODE_INJECTION: [
        re.compile(r"\b(?:union\s+(?:all\s+)?select|drop\s+(?:table|database)|insert\s+into|"
                   r"delete\s+from|update\s+\w+\s+set|xp_cmdshell|or\s+1\s*=\s*1|' ?or ?')\b"),
        re.compile(r"(?:;|\|\||&&|\|)\s*(?:rm|cat|curl|wget|bash|sh|nc|python|powershell|chmod)\b"),
        re.compile(r"\$\([^)]*\)|`[^`]{2,}`"),
        re.compile(r"(?:\.\./){2,}|\.\.\\\.\.\\|%2e%2e%2f"),
        re.compile(r"\b(?:eval|exec|__import__|os\.system|subprocess)\s*\("),
    ],
}

# Se evalúan sobre el texto original (antes de plegar).
_RAW_DELIMITER_RE: Final[re.Pattern[str]] = re.compile(r"<<<|>>>|<\|[^|>]{1,30}\|>")
_BASE64_BLOB_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9+/_-]{80,}={0,2}")
_HEX_BLOB_RE: Final[re.Pattern[str]] = re.compile(r"(?:[0-9a-fA-F]{2}[ :]?){40,}")
_ESCAPES_RE: Final[re.Pattern[str]] = re.compile(r"(?:\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|&#x?[0-9a-fA-F]+;){4,}")
_ENCODING_TALK_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:base ?64|rot ?13|hexadecimal|url[- ]?encod\w*|decodifica\w*|decode)\b.{0,40}"
    r"\b(?:esto|siguiente|lo siguiente|this|following|y ejecuta|and (?:run|follow))\b"
)


def scan(text: str) -> ScanResult:
    """Analiza ``text`` y devuelve las categorías de amenaza que encuentra."""
    if not text:
        return ScanResult()
    found: List[Threat] = []

    if _RAW_DELIMITER_RE.search(text):
        found.append(Threat.DELIMITER_ESCAPE)
    if (
        _BASE64_BLOB_RE.search(text)
        or _HEX_BLOB_RE.search(text)
        or _ESCAPES_RE.search(text)
        or _ENCODING_TALK_RE.search(fold(text))
    ):
        found.append(Threat.ENCODED_PAYLOAD)

    folded = fold(text)
    plain = fold(text, leet=False)  # conserva dígitos: cantidades como "5000 veces"
    for threat, patterns in _FOLDED_PATTERNS.items():
        # Markup y código se evalúan también sobre el original (el plegado altera símbolos).
        haystacks = (
            (text.lower(), folded, plain)
            if threat in (Threat.MARKUP_INJECTION, Threat.CODE_INJECTION)
            else (folded, plain)
        )
        if any(pattern.search(h) for pattern in patterns for h in haystacks):
            found.append(threat)
    return ScanResult(tuple(dict.fromkeys(found)))
