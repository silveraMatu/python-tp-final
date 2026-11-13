"""Aplicación FastAPI. Ejecutar con: ``uv run uvicorn app.api.main:app``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import ApiKeyAuthenticator
from app.api.deps import ContractLocks
from app.api.errors import register_error_handlers
from app.api.routers import contracts, documents, misc, review
from app.container import Services, build_services
from app.core.exceptions import HumanIAError
from app.core.config import Settings, get_settings

logger = logging.getLogger("humania.api")

DESCRIPTION = """\
API del agente de contratos laborales de HumanIA S.A.

- Autenticación: header `X-API-Key`. Roles: **REQUESTER** (arma el contrato) y
  **REVIEWER** (aprueba, rechaza o pide cambios).
- El texto de las cláusulas es el aprobado por la empresa: ni el agente ni la API lo modifican.
- La aprobación es siempre una decisión humana (`POST /contracts/{id}/review`).
"""


def create_app(services: Optional[Services] = None, settings: Optional[Settings] = None) -> FastAPI:
    """Crea la aplicación.

    Args:
        services: servicios ya construidos (tests). Si es ``None`` se construyen al
            arrancar a partir de la configuración.
        settings: configuración; por defecto la del entorno.
    """
    config = services.settings if services is not None else (settings or get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "services", None) is None:
            app.state.services = build_services(config)
        rag = app.state.services.rag
        if rag is not None and rag.count() == 0:
            try:  # base vacía: indexa las cláusulas aprobadas y los documentos disponibles
                rag.rebuild()
            except HumanIAError as exc:
                logger.warning("No se pudo indexar la base de conocimiento: %s", exc.message)
        if not config.api_users:
            logger.warning(
                "No hay usuarios configurados (HUMANIA_API_USERS): la API rechazará todo pedido"
            )
        yield

    app = FastAPI(
        title="HumanIA – Contratos laborales",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.locks = ContractLocks()
    app.state.authenticator = ApiKeyAuthenticator(config.api_users)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
        expose_headers=["X-Verification-Code", "Content-Disposition", "Location"],
    )
    register_error_handlers(app)
    for router in (misc.router, contracts.router, review.router, documents.router):
        app.include_router(router)
    return app


app = create_app()
