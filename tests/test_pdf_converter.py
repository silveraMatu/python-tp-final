from __future__ import annotations

import shutil
import stat
import textwrap
from datetime import date
from pathlib import Path

import pytest

from app.core.exceptions import PdfConversionError
from app.services.export_service import ExportService
from app.services.pdf_converter import LibreOfficeConverter
from app.services.pdf_tools import extract_full_text, find_verification_code
from app.services.template_service import ContractTemplateService
from tests.test_export_service import TEMPLATE, make_env


def script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "fake-soffice"
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def docx(tmp_path: Path) -> Path:
    path = tmp_path / "doc.docx"
    ContractTemplateService().init_base_template(str(path))
    return path


def test_missing_executable(docx: Path, tmp_path: Path) -> None:
    with pytest.raises(PdfConversionError, match="LibreOffice no está disponible"):
        LibreOfficeConverter("no-existe-soffice").convert(docx, tmp_path / "out")


def test_nonzero_exit_reports_stderr(docx: Path, tmp_path: Path) -> None:
    converter = LibreOfficeConverter(script(tmp_path, 'echo "boom interno" >&2\nexit 3\n'))
    with pytest.raises(PdfConversionError, match="boom interno"):
        converter.convert(docx, tmp_path / "out")


def test_success_without_output_file_is_an_error(docx: Path, tmp_path: Path) -> None:
    converter = LibreOfficeConverter(script(tmp_path, "exit 0\n"))
    with pytest.raises(PdfConversionError, match="no generó el PDF"):
        converter.convert(docx, tmp_path / "out")


def test_timeout(docx: Path, tmp_path: Path) -> None:
    converter = LibreOfficeConverter(script(tmp_path, "sleep 5\n"), timeout=0.3)
    with pytest.raises(PdfConversionError, match="superó el límite"):
        converter.convert(docx, tmp_path / "out")


def test_uses_an_isolated_profile_and_the_right_arguments(docx: Path, tmp_path: Path) -> None:
    log = tmp_path / "args.log"
    body = f"""\
        echo "$@" > {log}
        out=""
        while [ $# -gt 0 ]; do [ "$1" = "--outdir" ] && out="$2"; shift; done
        printf '%%PDF-1.4 fake' > "$out/doc.pdf"
        """
    result = LibreOfficeConverter(script(tmp_path, body)).convert(docx, tmp_path / "out")
    assert result == tmp_path / "out" / "doc.pdf"
    args = log.read_text()
    assert "-env:UserInstallation=file://" in args and "--headless" in args
    assert "--convert-to pdf:writer_pdf_Export" in args


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice no está instalado")
def test_real_libreoffice_export_end_to_end(tmp_path: Path) -> None:
    """Conversión real: las cláusulas, el código y la marca sobreviven al PDF."""
    env = make_env(tmp_path)
    exporter = ExportService(
        env.contracts,
        ContractTemplateService(today=lambda: date(2026, 11, 3)),
        LibreOfficeConverter(),
        TEMPLATE,
        tmp_path / "real-out",
    )
    draft = exporter.export_draft(env.contract_id, "rrhh")
    assert "BORRADOR" in extract_full_text(draft.pdf_path)

    env.approve()
    final = exporter.export_final(env.contract_id, "gerente")
    assert final.docx_path is not None and final.docx_path.is_file()
    assert find_verification_code(final.pdf_path) == final.verification_code
    assert "BORRADOR" not in extract_full_text(final.pdf_path)
    assert exporter.verify_final(env.contract_id).ok
