"""Dependencias de FastAPI: servicios, autenticación y bloqueos por contrato."""

from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Annotated, DefaultDict, Iterator, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.api.auth import ApiKeyAuthenticator, ApiUser, Role
from app.container import Services
from app.security.rate_limit import SlidingWindowLimiter

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API key del usuario")


class ContractLocks:
    """Serializa las operaciones que modifican un mismo contrato dentro del proceso.

    Evita que dos pedidos simultáneos lean el mismo estado y se pisen al guardar.
    """

    def __init__(self) -> None:
        self._locks: DefaultDict[UUID, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, contract_id: UUID) -> Iterator[None]:
        with self._guard:
            lock = self._locks[contract_id]
        with lock:
            yield


def get_services(request: Request) -> Services:
    services: Optional[Services] = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "El servicio aún no está listo")
    return services


def get_locks(request: Request) -> ContractLocks:
    locks: ContractLocks = request.app.state.locks
    return locks


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "desconocido"


def current_user(
    request: Request, api_key: Annotated[Optional[str], Depends(_api_key_header)]
) -> ApiUser:
    """Usuario autenticado por ``X-API-Key``; 401 si falta o no es válida.

    Los intentos fallidos se limitan por cliente (frena la fuerza bruta sobre las keys).
    """
    failures: SlidingWindowLimiter = request.app.state.auth_failure_limiter
    client = _client_key(request)
    if failures.is_blocked(client):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Demasiados intentos fallidos; esperá un momento",
            headers={"Retry-After": str(failures.retry_after(client))},
        )
    authenticator: ApiKeyAuthenticator = request.app.state.authenticator
    user = authenticator.authenticate(api_key)
    if user is None:
        failures.hit(client)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "API key ausente o inválida",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return user


def require_requester(user: Annotated[ApiUser, Depends(current_user)]) -> ApiUser:
    if user.role is not Role.REQUESTER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un solicitante puede hacer esto")
    return user


def require_reviewer(user: Annotated[ApiUser, Depends(current_user)]) -> ApiUser:
    if user.role is not Role.REVIEWER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un revisor puede hacer esto")
    return user


def limit_messages(request: Request, user: Annotated[ApiUser, Depends(require_requester)]) -> ApiUser:
    """Solicitante autenticado que todavía no agotó su cupo de mensajes por minuto."""
    limiter: SlidingWindowLimiter = request.app.state.message_limiter
    if not limiter.hit(user.name):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Enviaste demasiados mensajes seguidos; esperá un momento",
            headers={"Retry-After": str(limiter.retry_after(user.name))},
        )
    return user


ServicesDep = Annotated[Services, Depends(get_services)]
LocksDep = Annotated[ContractLocks, Depends(get_locks)]
UserDep = Annotated[ApiUser, Depends(current_user)]
RequesterDep = Annotated[ApiUser, Depends(require_requester)]
ReviewerDep = Annotated[ApiUser, Depends(require_reviewer)]
MessageUserDep = Annotated[ApiUser, Depends(limit_messages)]
