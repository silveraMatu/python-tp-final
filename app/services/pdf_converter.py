"""Conversión de DOCX a PDF."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.core.exceptions import PdfConversionError


class PdfConverter(Protocol):
    """Convierte un ``.docx`` en PDF."""

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        """Genera ``<output_dir>/<nombre>.pdf`` y devuelve su ruta.

        Raises:
            PdfConversionError: la conversión falló.
        """
        ...


class LibreOfficeConverter:
    """Conversión con ``soffice --headless``.

    Cada conversión usa un perfil de usuario temporal propio (LibreOffice no tolera
    bien dos procesos con el mismo perfil) y el número de conversiones simultáneas
    está acotado para no saturar la CPU.
    """

    def __init__(
        self, executable: str = "soffice", timeout: float = 90.0, max_parallel: int = 2
    ) -> None:
        self._executable = executable
        self._timeout = timeout
        self._slots = threading.BoundedSemaphore(max_parallel)

    def convert(self, docx_path: Path, output_dir: Path) -> Path:
        binary = shutil.which(self._executable)
        if binary is None:
            raise PdfConversionError(
                f"LibreOffice no está disponible ('{self._executable}'): no se puede generar el PDF"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        with self._slots, tempfile.TemporaryDirectory(prefix="lo-profile-") as profile:
            command = [
                binary,
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless",
                "--norestore",
                "--nologo",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ]
            try:
                completed = subprocess.run(
                    command, capture_output=True, text=True, timeout=self._timeout, check=False
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfConversionError(
                    f"La conversión a PDF superó el límite de {self._timeout:.0f} s"
                ) from exc
            except OSError as exc:
                raise PdfConversionError(f"No se pudo ejecutar LibreOffice: {exc}") from exc

        pdf_path = output_dir / f"{docx_path.stem}.pdf"
        if completed.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
            detail = (completed.stderr or completed.stdout or "sin detalle").strip()[-300:]
            raise PdfConversionError(f"LibreOffice no generó el PDF: {detail}")
        return pdf_path


def build_pdf_converter(settings: Settings) -> LibreOfficeConverter:
    """Construye el conversor a partir de la configuración."""
    return LibreOfficeConverter(settings.soffice_path, settings.pdf_timeout)
