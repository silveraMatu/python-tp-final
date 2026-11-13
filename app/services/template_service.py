"""Servicio de plantillas legales del contrato de trabajo (HumanIA S.A.).

Regla de negocio clave: INMUTABILIDAD LEGAL. El texto de las cláusulas vive en
:data:`STATIC_CLAUSES`, copiado textualmente de ``Contrato_Trabajo_Ejemplo.pdf``.
El LLM nunca redacta ni modifica cláusulas: solo se inyectan variables ya
validadas sobre marcadores Jinja2. Antes y después de renderizar se verifica
que el texto de cada cláusula coincida con el autorizado.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Optional

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from num2words import num2words

from app.core.exceptions import (
    ContractRenderError,
    HumanIAError,
    IncompleteContractDataError,
    TemplateNotFoundError,
    UnsupportedModalityError,
)
from app.schemas.contract import ContractData, EmploymentType, ValidationSeverity

# --------------------------------------------------------------------------- #
# Texto legal inmutable
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Clause:
    """Cláusula autorizada: título fijo y cuerpo con marcadores Jinja2."""

    ordinal: str
    title: str
    body: str

    @property
    def heading(self) -> str:
        return f"{self.ordinal} – {self.title}."

    @property
    def sha256(self) -> str:
        """Huella del texto autorizado (título + cuerpo con marcadores)."""
        return hashlib.sha256(f"{self.heading}\n{self.body}".encode("utf-8")).hexdigest()


STATIC_CLAUSES: Final[tuple[Clause, ...]] = (
    Clause(
        "PRIMERA",
        "Objeto",
        "EL EMPLEADO prestará servicios para EL EMPLEADOR en el puesto de "
        "{{ terms.puesto_funcion }}, realizando las tareas propias de dicha función y las que, "
        "siendo afines, le sean asignadas de acuerdo con las necesidades de la organización.",
    ),
    Clause(
        "SEGUNDA",
        "Inicio y modalidad",
        "La relación laboral comenzará el {{ terms.fecha_inicio }} y se celebra por tiempo "
        "indeterminado, conforme a la modalidad indicada en el cuadro de datos del contrato.",
    ),
    Clause(
        "TERCERA",
        "Jornada de trabajo",
        "La jornada laboral será {{ terms.jornada_laboral }}, respetando los límites y "
        "descansos establecidos por la normativa vigente.",
    ),
    Clause(
        "CUARTA",
        "Lugar de prestación",
        "Los servicios se prestarán en {{ terms.lugar_trabajo }}, sin perjuicio de las "
        "modalidades de trabajo que se acuerden por escrito.",
    ),
    Clause(
        "QUINTA",
        "Remuneración",
        "EL EMPLEADOR abonará a EL EMPLEADO una remuneración mensual bruta de "
        "{{ terms.remuneracion_bruta }}, sujeta a las retenciones y aportes de ley, pagadera "
        "dentro de los plazos legales.",
    ),
    Clause(
        "SEXTA",
        "Confidencialidad",
        "EL EMPLEADO se compromete a mantener la reserva y confidencialidad de la información "
        "a la que acceda con motivo de su trabajo, durante la vigencia de la relación y con "
        "posterioridad a su extinción.",
    ),
    Clause(
        "SÉPTIMA",
        "Normas internas",
        "EL EMPLEADO declara conocer y aceptar las políticas y reglamentos internos de EL "
        "EMPLEADOR, que le serán entregados al momento de su incorporación.",
    ),
    Clause(
        "OCTAVA",
        "Legislación aplicable",
        "El presente contrato se rige por la legislación laboral vigente y, ante cualquier "
        "controversia, las partes se someten a la jurisdicción de los tribunales competentes "
        "de la ciudad de Córdoba.",
    ),
)

DOCUMENT_TITLE: Final[str] = "CONTRATO DE TRABAJO"
DOCUMENT_SUBTITLE: Final[str] = "Por tiempo indeterminado"
INTRO_TEXT: Final[str] = (
    "En la ciudad de {{ lugar_celebracion }}, a los {{ dia_celebracion }} días del mes de "
    "{{ mes_celebracion }} de {{ anio_celebracion }}, entre {{ company.razon_social }}, CUIT "
    "{{ company.cuit }}, con domicilio en {{ company.domicilio_legal }}, en adelante "
    "“EL EMPLEADOR”, y {{ employee.nombre_completo }}, DNI {{ employee.dni }}, nacido/a el "
    "{{ employee.fecha_nacimiento }}, con domicilio en {{ employee.domicilio }}, en adelante "
    "“EL EMPLEADO”, se celebra el presente contrato de trabajo, sujeto a las siguientes "
    "cláusulas:"
)
CLOSING_TEXT: Final[str] = (
    "En prueba de conformidad, se firman dos ejemplares de un mismo tenor y a un solo efecto, "
    "en el lugar y fecha indicados al comienzo."
)
FOOTER_TEXT: Final[str] = "Código de verificación: {{ codigo_verificacion }}    Página "
DRAFT_HEADER: Final[str] = "BORRADOR – pendiente de aprobación humana"

CONTRACT_DATA_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("Empleador", "{{ company.razon_social }}"),
    ("CUIT del empleador", "{{ company.cuit }}"),
    ("Domicilio del empleador", "{{ company.domicilio_legal }}"),
    ("Empleado/a", "{{ employee.nombre_completo }}"),
    ("Documento de identidad", "DNI {{ employee.dni }}"),
    ("Fecha de nacimiento", "{{ employee.fecha_nacimiento }}"),
    ("Domicilio del empleado/a", "{{ employee.domicilio }}"),
    ("Puesto / función", "{{ terms.puesto_funcion }}"),
    ("Modalidad de contratación", "Contrato por tiempo indeterminado"),
    ("Fecha de inicio", "{{ terms.fecha_inicio }}"),
    ("Jornada laboral", "{{ terms.jornada_laboral }}"),
    (
        "Remuneración mensual bruta",
        "{{ terms.remuneracion_bruta }} (pesos argentinos, {{ terms.remuneracion_letras }})",
    ),
    ("Lugar de prestación de servicios", "{{ terms.lugar_trabajo }}"),
)
REVIEW_CONTROL_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("Datos validados por RR. HH.", "{{ revision.validado }}"),
    ("Inconsistencias detectadas", "{{ revision.inconsistencias }}"),
    ("Responsable que revisó", "{{ revision.responsable }}"),
    ("Aprobación final", "{{ revision.aprobacion }}"),
)
# Control de revisión sin completar (borrador y documentos sin aprobación registrada).
BLANK_REVIEW: Final[dict[str, str]] = {
    "validado": "☐ Sí      ☐ No",
    "inconsistencias": "Ninguna / Detalle: ____________________",
    "responsable": "Nombre: ______________ Fecha: ___/___/_____",
    "aprobacion": "☐ Aprobado         ☐ Requiere cambios",
}

SUPPORTED_MODALITIES: Final[frozenset[EmploymentType]] = frozenset({EmploymentType.INDETERMINATE})

_MONTHS_ES: Final[tuple[str, ...]] = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
_CLAUSE_HEADING_RE: Final[re.Pattern[str]] = re.compile(r"^[A-ZÁÉÍÓÚÑ]+ – .+\.$")
_UNRENDERED_TAG_RE: Final[re.Pattern[str]] = re.compile(r"\{\{|\}\}|\{%|%\}")

# --------------------------------------------------------------------------- #
# Formato es-AR (funciones puras y deterministas)
# --------------------------------------------------------------------------- #


def format_date(value: date) -> str:
    """``dd/mm/aaaa``."""
    return value.strftime("%d/%m/%Y")


def format_dni(dni: str) -> str:
    """``30123456`` -> ``30.123.456``."""
    return f"{int(dni):,}".replace(",", ".")


def format_ars(amount: Decimal) -> str:
    """``Decimal('2500000')`` -> ``$ 2.500.000``; con centavos ``$ 2.500.000,50``."""
    quantized = amount.quantize(Decimal("0.01"))
    pesos = int(quantized)
    cents = int((quantized - pesos) * 100)
    text = f"$ {pesos:,}".replace(",", ".")
    return f"{text},{cents:02d}" if cents else text


def amount_in_words(amount: Decimal) -> str:
    """Monto en letras en español, p. ej. ``dos millones quinientos mil``."""
    quantized = amount.quantize(Decimal("0.01"))
    pesos = int(quantized)
    cents = int((quantized - pesos) * 100)
    words = num2words(pesos, lang="es")
    words = re.sub(r"\bveintiuno\b(?= (?:mil|millones))", "veintiún", words)
    words = re.sub(r"\buno\b(?= (?:mil|millones))", "un", words)
    return f"{words} con {cents:02d}/100" if cents else words


# --------------------------------------------------------------------------- #
# Opciones de render
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReviewRecord:
    """Decisión humana registrada, para completar el control de revisión del final."""

    reviewer: str
    reviewed_on: date


@dataclass(frozen=True)
class RenderOptions:
    """Variantes de render que no tocan las cláusulas.

    Attributes:
        draft: agrega el encabezado de borrador.
        review: si se informa, completa el control de revisión humana.
    """

    draft: bool = False
    review: Optional[ReviewRecord] = None


def review_context(review: Optional[ReviewRecord]) -> dict[str, str]:
    """Textos del control de revisión (en blanco si no hay decisión registrada)."""
    if review is None:
        return dict(BLANK_REVIEW)
    return {
        "validado": "☒ Sí      ☐ No",
        "inconsistencias": "Ninguna",
        "responsable": f"Nombre: {review.reviewer} Fecha: {format_date(review.reviewed_on)}",
        "aprobacion": "☒ Aprobado         ☐ Requiere cambios",
    }


# --------------------------------------------------------------------------- #
# Servicio
# --------------------------------------------------------------------------- #


class ContractTemplateService:
    """Genera la plantilla base y renderiza contratos sin tocar cláusulas legales."""

    def __init__(
        self,
        city: str = "Córdoba",
        today: Callable[[], date] = date.today,
    ) -> None:
        """
        Args:
            city: ciudad de celebración (encabezado del contrato).
            today: proveedor de la fecha de celebración (inyectable para tests).
        """
        self._city = city
        self._today = today

    # ------------------------------------------------------------------ #
    # Generación de la plantilla base
    # ------------------------------------------------------------------ #

    def init_base_template(self, output_path: str) -> None:
        """Genera la plantilla ``.docx`` parametrizada con tags Jinja2.

        Replica la estructura de ``Contrato_Trabajo_Ejemplo.pdf``. Cada tag queda
        dentro de un único *run* para que Jinja lo reconozca.
        """
        try:
            document = Document()
            self._configure_styles(document)

            self._add_paragraph(
                document, DOCUMENT_TITLE, bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER
            )
            self._add_paragraph(
                document, DOCUMENT_SUBTITLE, size=12, align=WD_ALIGN_PARAGRAPH.CENTER, after=14
            )
            self._add_paragraph(
                document, INTRO_TEXT, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=12
            )

            self._add_paragraph(document, "DATOS DEL CONTRATO", bold=True, before=6, after=4)
            self._add_key_value_table(document, CONTRACT_DATA_ROWS)

            self._add_paragraph(document, "CLÁUSULAS", bold=True, before=12, after=4)
            for clause in STATIC_CLAUSES:
                heading = self._add_paragraph(
                    document, clause.heading, bold=True, before=8, after=2
                )
                heading.paragraph_format.keep_with_next = True
                self._add_paragraph(
                    document, clause.body, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=4
                )

            self._add_paragraph(
                document, CLOSING_TEXT, align=WD_ALIGN_PARAGRAPH.JUSTIFY, before=12, after=36
            )
            self._add_signature_block(document)

            self._add_paragraph(
                document, "CONTROL DE REVISIÓN HUMANA", bold=True, before=24, after=4
            )
            self._add_key_value_table(document, REVIEW_CONTROL_ROWS)

            self._add_header(document)
            self._add_footer(document)

            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            document.save(str(target))
        except Exception as exc:
            raise ContractRenderError(
                f"No se pudo generar la plantilla base en {output_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Verificación de integridad
    # ------------------------------------------------------------------ #

    def verify_template(self, template_path: str) -> None:
        """Comprueba que la plantilla contenga exactamente las cláusulas autorizadas.

        Raises:
            TemplateNotFoundError: la plantilla no existe.
            ContractRenderError: falta, sobra o difiere el texto de alguna cláusula.
        """
        path = Path(template_path)
        if not path.is_file():
            raise TemplateNotFoundError(template_path)
        try:
            document = Document(str(path))
        except Exception as exc:
            raise ContractRenderError(f"La plantilla {template_path} no es un .docx válido: {exc}") from exc

        violations = self._clause_violations(
            [p.text for p in document.paragraphs],
            [(c.heading, c.body) for c in STATIC_CLAUSES],
        )
        if violations:
            raise ContractRenderError(
                "La plantilla no respeta las cláusulas legales autorizadas: " + "; ".join(violations)
            )

    # ------------------------------------------------------------------ #
    # Renderizado
    # ------------------------------------------------------------------ #

    def render_contract(
        self,
        contract_data: ContractData,
        template_path: str,
        output_path: str,
        options: RenderOptions = RenderOptions(),
    ) -> str:
        """Inyecta los datos validados en la plantilla y guarda el ``.docx``.

        ``options`` solo cambia el encabezado de borrador y el control de revisión;
        las cláusulas legales son siempre las autorizadas.

        Returns:
            Ruta absoluta del documento generado.

        Raises:
            IncompleteContractDataError: ``contract_data.is_complete`` es False.
            UnsupportedModalityError: no hay plantilla aprobada para la modalidad.
            TemplateNotFoundError: la plantilla no existe.
            ContractRenderError: falla de renderizado o de verificación de cláusulas.
        """
        employee, company, terms = (
            contract_data.employee,
            contract_data.company,
            contract_data.terms,
        )
        if not contract_data.is_complete or employee is None or company is None or terms is None:
            raise IncompleteContractDataError(
                missing_fields=contract_data.get_missing_fields(),
                invalid_fields=[
                    flag.field_name
                    for flag in contract_data.validation_flags
                    if not flag.is_valid or flag.conflict_detected or flag.severity is ValidationSeverity.ERROR
                ],
            )
        if terms.modalidad not in SUPPORTED_MODALITIES:
            raise UnsupportedModalityError(terms.modalidad.value)

        self.verify_template(template_path)

        output = Path(output_path).resolve()
        try:
            context = self.build_context(contract_data, options)
            template = DocxTemplate(template_path)
            template.render(
                context,
                jinja_env=Environment(undefined=StrictUndefined),
                autoescape=True,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            template.save(str(output))
            self._verify_rendered(output, context)
        except HumanIAError:
            output.unlink(missing_ok=True)
            raise
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise ContractRenderError(f"No se pudo renderizar el contrato: {exc}") from exc

        return str(output)

    def build_context(
        self, contract_data: ContractData, options: RenderOptions = RenderOptions()
    ) -> dict[str, Any]:
        """Construye el contexto de render (todo texto ya formateado, es-AR).

        Raises:
            IncompleteContractDataError: faltan secciones del contrato.
        """
        employee, company, terms = (
            contract_data.employee,
            contract_data.company,
            contract_data.terms,
        )
        if employee is None or company is None or terms is None:
            raise IncompleteContractDataError(missing_fields=contract_data.get_missing_fields())

        today = self._today()
        context: dict[str, Any] = {
            "lugar_celebracion": self._city,
            "dia_celebracion": str(today.day),
            "mes_celebracion": _MONTHS_ES[today.month - 1],
            "anio_celebracion": str(today.year),
            "employee": {
                "nombre": employee.nombre,
                "apellido": employee.apellido,
                "nombre_completo": f"{employee.nombre} {employee.apellido}",
                "dni": format_dni(employee.dni),
                "cuil": employee.cuil,
                "domicilio": employee.domicilio,
                "fecha_nacimiento": format_date(employee.fecha_nacimiento),
            },
            "company": {
                "razon_social": company.razon_social,
                "cuit": company.cuit,
                "domicilio_legal": company.domicilio_legal,
                "apoderado_nombre": company.apoderado_nombre,
                "apoderado_cargo": company.apoderado_cargo,
            },
            "terms": {
                "puesto_funcion": terms.puesto_funcion,
                "fecha_inicio": format_date(terms.fecha_inicio),
                "modalidad": terms.modalidad.value,
                "remuneracion_bruta": format_ars(terms.remuneracion_bruta),
                "remuneracion_letras": amount_in_words(terms.remuneracion_bruta),
                "jornada_laboral": terms.jornada_laboral,
                "lugar_trabajo": terms.lugar_trabajo,
            },
        }
        context["estado_documento"] = DRAFT_HEADER if options.draft else ""
        context["revision"] = review_context(options.review)
        context["codigo_verificacion"] = self.verification_code(context)
        return context

    @staticmethod
    def rendered_clauses(context: dict[str, Any]) -> list[tuple[str, str]]:
        """Cláusulas autorizadas con las variables del contexto ya reemplazadas."""
        env = Environment(undefined=StrictUndefined)
        return [(c.heading, env.from_string(c.body).render(context)) for c in STATIC_CLAUSES]

    def verification_code(self, context: dict[str, Any]) -> str:
        """Código corto (``XXXX-XXXX-XXXX``) derivado del contenido: cláusulas + datos.

        Dos documentos con las mismas cláusulas y datos tienen el mismo código; si
        cambia cualquiera de los dos, cambia el código.
        """
        data_keys = (
            "lugar_celebracion", "dia_celebracion", "mes_celebracion", "anio_celebracion",
            "employee", "company", "terms",
        )  # fmt: skip
        payload = json.dumps(
            {
                "clauses": self.rendered_clauses(context),
                "data": {key: context[key] for key in data_keys},
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()
        return f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"

    # ------------------------------------------------------------------ #
    # Verificación posterior al render
    # ------------------------------------------------------------------ #

    def _verify_rendered(self, output: Path, context: dict[str, Any]) -> None:
        """El documento final debe tener las cláusulas autorizadas y ningún tag sin resolver."""
        document = Document(str(output))
        expected = self.rendered_clauses(context)

        violations = self._clause_violations([p.text for p in document.paragraphs], expected)
        if violations:
            raise ContractRenderError(
                "El documento generado altera las cláusulas legales: " + "; ".join(violations)
            )

        leftovers = [text for text in self._all_texts(document) if _UNRENDERED_TAG_RE.search(text)]
        if leftovers:
            raise ContractRenderError(f"Quedaron marcadores sin resolver: {leftovers[0]!r}")

    @staticmethod
    def _clause_violations(
        paragraphs: Sequence[str], expected: Sequence[tuple[str, str]]
    ) -> list[str]:
        """Compara los párrafos con las cláusulas esperadas (encabezado + cuerpo)."""
        violations: list[str] = []
        known_headings = {heading for heading, _ in expected}

        for heading, body in expected:
            occurrences = [i for i, text in enumerate(paragraphs) if text == heading]
            if len(occurrences) != 1:
                violations.append(f"cláusula '{heading}' presente {len(occurrences)} veces")
                continue
            index = occurrences[0]
            actual = paragraphs[index + 1] if index + 1 < len(paragraphs) else None
            if actual != body:
                violations.append(f"el texto de la cláusula '{heading}' difiere del autorizado")

        for text in paragraphs:
            if _CLAUSE_HEADING_RE.match(text) and text not in known_headings:
                violations.append(f"cláusula no autorizada '{text}'")
        return violations

    @staticmethod
    def _all_texts(document: DocxDocument) -> list[str]:
        """Texto de párrafos de cuerpo, celdas de tablas y pies de página."""
        texts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                texts.extend(cell.text for cell in row.cells)
        for section in document.sections:
            texts.extend(p.text for p in section.header.paragraphs)
            texts.extend(p.text for p in section.footer.paragraphs)
        return texts

    # ------------------------------------------------------------------ #
    # Helpers de construcción del .docx
    # ------------------------------------------------------------------ #

    @staticmethod
    def _configure_styles(document: DocxDocument) -> None:
        normal = document.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(10.5)
        r_pr = normal.element.get_or_add_rPr()
        r_fonts = r_pr.find(qn("w:rFonts"))
        if r_fonts is None:
            r_fonts = OxmlElement("w:rFonts")
            r_pr.append(r_fonts)
        r_fonts.set(qn("w:eastAsia"), "Arial")

    @staticmethod
    def _add_paragraph(
        container: DocxDocument | _Cell,
        text: str,
        *,
        bold: bool = False,
        size: float | None = None,
        align: WD_ALIGN_PARAGRAPH | None = None,
        before: float = 0,
        after: float = 0,
    ) -> Paragraph:
        paragraph = container.add_paragraph()
        run = paragraph.add_run(text)  # un solo run: los tags Jinja no se fragmentan
        run.bold = bold
        if size is not None:
            run.font.size = Pt(size)
        if align is not None:
            paragraph.alignment = align
        paragraph.paragraph_format.space_before = Pt(before)
        paragraph.paragraph_format.space_after = Pt(after)
        return paragraph

    @staticmethod
    def _shade(cell: _Cell, fill: str) -> None:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), fill)
        cell._tc.get_or_add_tcPr().append(shading)

    def _add_key_value_table(
        self, document: DocxDocument, rows: Sequence[tuple[str, str]]
    ) -> Table:
        table = document.add_table(rows=0, cols=2)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        for label, value in rows:
            label_cell, value_cell = table.add_row().cells
            label_cell.paragraphs[0].add_run(label).bold = True
            value_cell.paragraphs[0].add_run(value)  # un solo run por celda
            self._shade(label_cell, "EDEDED")
        return table

    def _add_signature_block(self, document: DocxDocument) -> None:
        table = document.add_table(rows=1, cols=2)
        left, right = table.rows[0].cells
        for cell, lines in (
            (left, ("p. {{ company.razon_social }}", "Representante autorizado (EMPLEADOR)")),
            (right, ("{{ employee.nombre_completo }}", "DNI {{ employee.dni }} (EMPLEADO/A)")),
        ):
            cell.paragraphs[0].add_run(lines[0])
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            second = cell.add_paragraph()
            second.add_run(lines[1])
            second.alignment = WD_ALIGN_PARAGRAPH.CENTER

    @staticmethod
    def _add_header(document: DocxDocument) -> None:
        """Encabezado con el estado del documento (vacío en el final)."""
        header = document.sections[0].header.paragraphs[0]
        header.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = header.add_run("{{ estado_documento }}")  # un solo run
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

    @staticmethod
    def _add_footer(document: DocxDocument) -> None:
        footer = document.sections[0].footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = footer.add_run(FOOTER_TEXT)
        run.font.size = Pt(8)

        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        field_run = OxmlElement("w:r")
        field_props = OxmlElement("w:rPr")
        field_size = OxmlElement("w:sz")
        field_size.set(qn("w:val"), "16")  # 8 pt, igual que el resto del pie
        field_props.append(field_size)
        field_run.append(field_props)
        field_text = OxmlElement("w:t")
        field_text.text = "1"
        field_run.append(field_text)
        field.append(field_run)
        footer._p.append(field)
