"""Mapeo de excepciones de dominio a respuestas HTTP."""

from __future__ import annotations

import logging
from typing import Final, List, Tuple, Type

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import (
    ConflictNotFoundError,
    ContractAlreadyExistsError,
    ContractNotFoundError,
    ContractRenderError,
    ExportIntegrityError,
    ExtractionError,
    HumanIAError,
    IncompleteContractDataError,
    InvalidStateTransitionError,
    LLMUnavailableError,
    TemplateNotFoundError,
    UnsupportedDocumentError,
    UnsupportedModalityError,
)

logger = logging.getLogger("humania.api")

# (excepción, HTTP, código); se evalúa en orden, de lo más específico a lo más general.
_MAPPING: Final[List[Tuple[Type[HumanIAError], int, str]]] = [
    (ContractNotFoundError, status.HTTP_404_NOT_FOUND, "contract_not_found"),
    (ContractAlreadyExistsError, status.HTTP_409_CONFLICT, "contract_already_exists"),
    (InvalidStateTransitionError, status.HTTP_409_CONFLICT, "invalid_state_transition"),
    (ConflictNotFoundError, status.HTTP_409_CONFLICT, "no_pending_conflict"),
    (ExportIntegrityError, status.HTTP_409_CONFLICT, "export_integrity_error"),
    (IncompleteContractDataError, status.HTTP_422_UNPROCESSABLE_CONTENT, "incomplete_contract"),
    (UnsupportedDocumentError, status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported_document"),
    (UnsupportedModalityError, status.HTTP_501_NOT_IMPLEMENTED, "unsupported_modality"),
    (ExtractionError, status.HTTP_502_BAD_GATEWAY, "extraction_failed"),
    (LLMUnavailableError, status.HTTP_503_SERVICE_UNAVAILABLE, "llm_unavailable"),
    (TemplateNotFoundError, status.HTTP_500_INTERNAL_SERVER_ERROR, "template_not_found"),
    (ContractRenderError, status.HTTP_500_INTERNAL_SERVER_ERROR, "render_failed"),
]
# Errores internos: el detalle técnico se registra, no se devuelve.
_GENERIC_DETAIL: Final[dict[str, str]] = {
    "template_not_found": "La plantilla del contrato no está disponible.",
    "render_failed": "No se pudo generar el documento. Intentá de nuevo o avisá a soporte.",
}


def classify(exc: HumanIAError) -> Tuple[int, str]:
    """HTTP y código para una excepción de dominio."""
    for exception_type, http_status, code in _MAPPING:
        if isinstance(exc, exception_type):
            return http_status, code
    return status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error"


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HumanIAError)
    http_status, code = classify(exc)
    if http_status >= 500 and http_status != status.HTTP_501_NOT_IMPLEMENTED:
        logger.error("%s en %s %s: %s", code, request.method, request.url.path, exc.message)
    detail = _GENERIC_DETAIL.get(code, exc.message)
    return JSONResponse(status_code=http_status, content={"error": code, "detail": detail})


def register_error_handlers(app: FastAPI) -> None:
    """Registra el manejador para todas las excepciones de dominio."""
    app.add_exception_handler(HumanIAError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)


_HTTP_CODES: Final[dict[int, str]] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "service_unavailable",
}


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Los errores HTTP (401, 403, 413, 429, ...) usan el mismo formato ``{error, detail}``."""
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": code, "detail": str(exc.detail)},
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Errores de validación sin eco del contenido enviado (no se devuelve ``input``)."""
    assert isinstance(exc, RequestValidationError)
    problems = [
        f"{'.'.join(str(part) for part in err['loc'] if part != 'body')}: {err['msg']}"
        for err in exc.errors()[:5]
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"error": "validation_error", "detail": "; ".join(problems)[:300]},
    )
