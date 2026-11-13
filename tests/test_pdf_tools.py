from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.services import pdf_tools


def make_pdf(path: Path, pages: int = 2) -> Path:
    document = pymupdf.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 45), "ENCABEZADO", fontsize=9)
        page.insert_text((72, 100), f"Cuerpo de la pagina {number}", fontsize=11)
        page.insert_text((72, 800), f"Código de verificación: 1E28-0AC3-0B0B   Página {number}", fontsize=8)
    document.save(str(path))
    document.close()
    return path


def test_body_text_excludes_header_and_footer(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf")
    body = pdf_tools.extract_body_text(pdf)
    assert "Cuerpo de la pagina 1" in body and "Cuerpo de la pagina 2" in body
    assert "ENCABEZADO" not in body and "verificación" not in body
    full = pdf_tools.extract_full_text(pdf)
    assert "ENCABEZADO" in full and "verificación" in full


def test_extract_from_bytes_and_find_code(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", pages=1)
    assert pdf_tools.find_verification_code(pdf.read_bytes()) == "1E28-0AC3-0B0B"
    plain = pymupdf.open()
    plain.new_page().insert_text((72, 100), "sin codigo")
    assert pdf_tools.find_verification_code(bytes(plain.tobytes())) is None


def test_clause_violations_ignore_line_wrapping_and_flag_changes() -> None:
    text = "PRIMERA – Objeto.\nEL EMPLEADO prestará\nservicios.\n\nSEGUNDA – Plazo.\nUn año."
    expected = [
        ("PRIMERA – Objeto.", "EL EMPLEADO prestará servicios."),
        ("SEGUNDA – Plazo.", "Un año."),
    ]
    assert pdf_tools.clause_violations(text, expected) == []

    altered = text.replace("Un año", "Dos años")
    violations = pdf_tools.clause_violations(altered, expected)
    assert len(violations) == 1 and "SEGUNDA" in violations[0]


def test_normalize_whitespace_removes_soft_hyphens() -> None:
    assert pdf_tools.normalize_whitespace("a­b \n  c") == "ab c"


def test_watermark_is_added_to_every_page_and_keeps_content(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", pages=3)
    pdf_tools.apply_watermark(pdf, "BORRADOR")
    with pymupdf.open(str(pdf)) as document:
        assert document.page_count == 3
        assert all("BORRADOR" in page.get_text() for page in document)
        assert all("Cuerpo de la pagina" in page.get_text() for page in document)
    assert not list(tmp_path.glob("*.tmp")) and [p.name for p in tmp_path.iterdir()] == ["a.pdf"]


def test_set_metadata(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", pages=1)
    pdf_tools.set_metadata(pdf, "Contrato", "Contrato 123", "estado=FINAL", "HumanIA S.A.")
    with pymupdf.open(str(pdf)) as document:
        assert document.metadata["title"] == "Contrato"
        assert document.metadata["subject"] == "Contrato 123"
        assert document.metadata["keywords"] == "estado=FINAL"
        assert document.metadata["author"] == "HumanIA S.A."


def test_failed_edit_leaves_original_untouched(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "a.pdf", pages=1)
    before = pdf.read_bytes()
    with pytest.raises(RuntimeError):
        with pdf_tools._editing(pdf):
            raise RuntimeError("falla a mitad de la edición")
    assert pdf.read_bytes() == before and [p.name for p in tmp_path.iterdir()] == ["a.pdf"]
