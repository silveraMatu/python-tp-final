"""Almacén en disco de los adjuntos del chat.

Los archivos se guardan con un nombre aleatorio (nunca el que envió el usuario), en una
carpeta por contrato y con permisos restringidos, de modo que el nombre original no puede
usarse para escribir o leer fuera del almacén.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from app.core.exceptions import UnsupportedDocumentError
from app.repositories.chat import NewAttachment
from app.security.text import normalize_input

MEDIA_TYPES: Final[dict[str, str]] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_MAX_NAME_CHARS: Final[int] = 120
_UNSAFE_NAME_RE: Final[re.Pattern[str]] = re.compile(r"[^\w.\- ()áéíóúüñÁÉÍÓÚÜÑ]")


@dataclass(frozen=True)
class Upload:
    """Archivo recibido en un mensaje."""

    filename: str
    data: bytes


def safe_display_name(filename: str) -> str:
    """Nombre solo para mostrar: sin rutas, sin caracteres de control ni marcado."""
    base = normalize_input(filename).replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_NAME_RE.sub("_", base).strip(" .") or "archivo"
    return cleaned[:_MAX_NAME_CHARS]


class AttachmentStore:
    """Guarda y localiza adjuntos."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    def save(self, contract_id: UUID, upload: Upload) -> NewAttachment:
        """Escribe el archivo y devuelve sus datos para registrarlo.

        Raises:
            UnsupportedDocumentError: extensión no permitida.
        """
        extension = Path(safe_display_name(upload.filename)).suffix.lower()
        media_type = MEDIA_TYPES.get(extension)
        if media_type is None:
            raise UnsupportedDocumentError(f"Tipo de archivo no soportado: '{extension}'")

        folder = self._folder(contract_id)
        stored_name = f"{uuid4().hex}{extension}"
        target = folder / stored_name
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(upload.data)
        return NewAttachment(
            filename=safe_display_name(upload.filename),
            media_type=media_type,
            size_bytes=len(upload.data),
            sha256=hashlib.sha256(upload.data).hexdigest(),
            stored_name=stored_name,
        )

    def path_of(self, contract_id: UUID, stored_name: str) -> Path:
        """Ruta de un adjunto; falla si saldría del almacén."""
        path = (self._folder(contract_id, create=False) / stored_name).resolve()
        if self._root not in path.parents:
            raise UnsupportedDocumentError("Ruta de adjunto inválida")
        return path

    def delete(self, contract_id: UUID, stored_name: str) -> None:
        """Borra un adjunto (limpieza ante un error al registrar el mensaje)."""
        try:
            self.path_of(contract_id, stored_name).unlink(missing_ok=True)
        except UnsupportedDocumentError:
            pass

    def _folder(self, contract_id: UUID, create: bool = True) -> Path:
        folder = self._root / str(contract_id)
        if create:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return folder
