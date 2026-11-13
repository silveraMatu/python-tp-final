"""Autenticación por API key con roles.

Las keys nunca se guardan: la configuración solo contiene su hash SHA-256.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence

from app.core.config import ApiUserConfig

KEY_PREFIX = "hk_"


class Role(str, Enum):
    """REQUESTER arma contratos; REVIEWER decide sobre ellos."""

    REQUESTER = "REQUESTER"
    REVIEWER = "REVIEWER"


@dataclass(frozen=True)
class ApiUser:
    """Usuario autenticado."""

    name: str
    role: Role


def hash_api_key(key: str) -> str:
    """SHA-256 hexadecimal de una API key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Devuelve ``(key, sha256)``. La key se muestra una sola vez; se guarda solo el hash."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_api_key(key)


class ApiKeyAuthenticator:
    """Resuelve una API key a un usuario, comparando en tiempo constante."""

    def __init__(self, users: Sequence[ApiUserConfig]) -> None:
        self._users = [(user.key_sha256, ApiUser(user.name, Role(user.role))) for user in users]

    def authenticate(self, key: Optional[str]) -> Optional[ApiUser]:
        if not key:
            return None
        digest = hash_api_key(key)
        found: Optional[ApiUser] = None
        for stored, user in self._users:  # recorre todos: no filtra cuál coincidió por tiempo
            if hmac.compare_digest(digest, stored):
                found = user
        return found
