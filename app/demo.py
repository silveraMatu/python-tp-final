"""Datos de demostración para desarrollar un frontend sin armar todo a mano.

Crea, en una carpeta aparte, una base con usuarios de keys conocidas y contratos en cada
estado (con chat, adjuntos y decisiones de revisión). **Solo para uso local**: las keys son
públicas.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import pymupdf

from app.agent import replies
from app.api.auth import hash_api_key
from app.container import Services, build_services
from app.core.config import ApiUserConfig, Settings
from app.schemas.extraction import FieldCandidate
from app.services.attachment_store import Upload

DEMO_USERS: Dict[str, tuple[str, str]] = {
    "ana": ("REQUESTER", "demo-ana-key"),
    "carlos": ("REQUESTER", "demo-carlos-key"),
    "bruno": ("REVIEWER", "demo-bruno-key"),
}

EMPLOYEE_VALUES: Dict[str, str] = {
    "employee.nombre": "Juan",
    "employee.apellido": "Pérez",
    "employee.dni": "30123456",
    "employee.cuil": "20-30123456-3",
    "employee.domicilio": "Calle Falsa 742, Córdoba",
    "employee.fecha_nacimiento": "1995-03-15",
}
COMPANY_VALUES: Dict[str, str] = {
    "company.razon_social": "HumanIA S.A.",
    "company.cuit": "30-71234567-1",
    "company.domicilio_legal": "Av. Ejemplo 1234, Córdoba",
    "company.apoderado_nombre": "María Gómez",
    "company.apoderado_cargo": "Gerente de RR. HH.",
}
TERMS_VALUES: Dict[str, str] = {
    "terms.puesto_funcion": "Desarrollador de Software",
    "terms.fecha_inicio": "2026-11-09",
    "terms.modalidad": "INDETERMINATE",
    "terms.remuneracion_bruta": "2500000",
    "terms.jornada_laboral": "de lunes a viernes, de 9:00 a 17:00 hs",
    "terms.lugar_trabajo": "las oficinas de HumanIA S.A., Av. Ejemplo 1234, Córdoba",
}
FULL_VALUES = {**EMPLOYEE_VALUES, **COMPANY_VALUES, **TERMS_VALUES}
FULL_MESSAGE = (
    "Necesito un contrato para Juan Pérez, DNI 30.123.456, CUIL 20-30123456-3, nacido el "
    "15/03/1995, domicilio Calle Falsa 742, Córdoba. La empresa es HumanIA S.A., CUIT "
    "30-71234567-1, domicilio legal Av. Ejemplo 1234, Córdoba; firma María Gómez, Gerente de "
    "RR. HH. Ingresa el 9 de noviembre de 2026 como Desarrollador de Software, por tiempo "
    "indeterminado, sueldo bruto $ 2.500.000, de lunes a viernes de 9:00 a 17:00 hs, en las "
    "oficinas de HumanIA S.A., Av. Ejemplo 1234, Córdoba."
)


@dataclass(frozen=True)
class DemoContract:
    """Contrato creado por el script, para mostrar al terminar."""

    id: str
    owner: str
    status: str
    description: str


@dataclass(frozen=True)
class DemoInfo:
    """Resultado de :func:`seed_demo`."""

    directory: Path
    env_file: Path
    contracts: List[DemoContract]


def _batch(values: Dict[str, str], confidence: float = 0.97) -> List[FieldCandidate]:
    return [
        FieldCandidate(field_name=path, value=value, confidence_score=confidence, source="demo")
        for path, value in values.items()
    ]


def _fake_dni_png() -> bytes:
    """Imagen de un DNI ficticio, para el adjunto de ejemplo."""
    page = pymupdf.open().new_page(width=420, height=260)
    page.insert_text((24, 44), "DOCUMENTO NACIONAL DE IDENTIDAD (FICTICIO)", fontsize=11)
    page.insert_text((24, 100), "Apellido: PEREZ", fontsize=15)
    page.insert_text((24, 135), "Nombre: JUAN", fontsize=15)
    page.insert_text((24, 170), "DNI: 30.123.456", fontsize=15)
    page.insert_text((24, 205), "Fecha de nacimiento: 15 MAR 1995", fontsize=13)
    return bytes(page.get_pixmap(dpi=110).tobytes("png"))


class _Seeder:
    def __init__(self, services: Services) -> None:
        self.s = services
        self.created: List[DemoContract] = []

    def contract(self, owner: str, description: str) -> str:
        return str(self.s.contracts.start(owner).id)

    def register(self, contract_id: str, owner: str, description: str) -> None:
        contract = self.s.contracts.get(__import__("uuid").UUID(contract_id))
        self.created.append(DemoContract(contract_id, owner, contract.status.value, description))

    def say(
        self,
        contract_id: str,
        owner: str,
        message: str,
        values: Dict[str, str],
        confidence: float = 0.97,
        uploads: Sequence[Upload] = (),
        intent: str = "PROVIDE_DATA",
    ) -> None:
        """Aplica datos y anota el intercambio como lo haría el agente."""
        from uuid import UUID

        cid = UUID(contract_id)
        applied = self.s.contracts.apply_extraction(cid, _batch(values, confidence), owner)
        contract = applied.contract
        lines: List[str] = []
        if applied.accepted:
            lines.append(
                f"Registré {len(applied.accepted)} dato(s):\n"
                + "\n".join(
                    f"- {replies.label(p)}: {replies.display_value(p, contract.collected_values[p])}"
                    for p in applied.accepted
                )
            )
        if applied.conflicts:
            lines.append(
                f"{len(applied.conflicts)} dato(s) quedaron pendientes de tu confirmación: "
                + ", ".join(replies.label(p) for p in applied.conflicts)
                + "."
            )
        lines.append(replies.next_step(contract))
        self.s.chat.record_exchange(
            cid, owner, message, uploads, "\n\n".join(lines), intent, "demo"
        )

    def event(self, contract_id: str, actor: str, text: str) -> None:
        from uuid import UUID

        self.s.chat.record_event(UUID(contract_id), actor, text)


def seed_demo(directory: Path, force: bool = False) -> DemoInfo:
    """Crea la base de demostración en ``directory``.

    Raises:
        FileExistsError: la carpeta existe y no se pidió ``force``.
    """
    from uuid import UUID

    if directory.exists():
        if not force:
            raise FileExistsError(f"{directory} ya existe (usá --force para recrearla)")
        shutil.rmtree(directory)
    directory.mkdir(parents=True)

    users = [
        ApiUserConfig(name=name, role=role, key_sha256=hash_api_key(key))  # type: ignore[arg-type]
        for name, (role, key) in DEMO_USERS.items()
    ]
    settings = Settings(
        api_users=users,
        database_path=directory / "contracts.db",
        output_dir=directory / "output",
        attachments_dir=directory / "attachments",
        chroma_path=directory / "chroma",
        knowledge_dir=directory / "knowledge",
        _env_file=None,
    )
    services = build_services(settings, with_rag=False)
    seeder = _Seeder(services)
    contracts = services.contracts

    # 1. Nuevo, sin datos
    cid = seeder.contract("ana", "")
    seeder.register(cid, "ana", "Nuevo, sin datos ni chat (INITIAL)")

    # 2. Recolectando datos (solo el empleado)
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", "El empleado es Juan Pérez, DNI 30.123.456, CUIL 20-30123456-3, nacido el 15/03/1995, vive en Calle Falsa 742, Córdoba.", EMPLOYEE_VALUES)
    seeder.register(cid, "ana", "Recolectando datos: solo falta la empresa y las condiciones (COLLECTING_DATA)")

    # 3. Dato pendiente de confirmación
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", "", {"employee.dni": "30123456"}, confidence=0.55,
               uploads=[Upload("dni.png", _fake_dni_png())])
    seeder.register(cid, "ana", "Con un dato de baja confianza esperando confirmación y un adjunto (CONFLICT_DETECTED)")

    # 4. Completo, listo para enviar
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", FULL_MESSAGE, FULL_VALUES)
    seeder.register(cid, "ana", "Datos completos: se puede ver el borrador y enviar a revisión (COLLECTING_DATA)")

    # 5. Pendiente de revisión
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", FULL_MESSAGE, FULL_VALUES)
    contracts.submit_for_review(UUID(cid), "ana")
    seeder.event(cid, "ana", "Enviaste el borrador a revisión humana.")
    seeder.register(cid, "ana", "En la bandeja del revisor (PENDING_HUMAN_REVIEW)")

    # 6. Aprobado
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", FULL_MESSAGE, FULL_VALUES)
    contracts.submit_for_review(UUID(cid), "ana")
    seeder.event(cid, "ana", "Enviaste el borrador a revisión humana.")
    contracts.review(UUID(cid), True, "bruno", "Todo en orden")
    seeder.event(cid, "bruno", "El revisor bruno aprobó el contrato. Comentario: «Todo en orden»")
    seeder.register(cid, "ana", "Aprobado: se puede descargar el final y verificarlo (APPROVED)")

    # 7. Rechazado
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", FULL_MESSAGE, FULL_VALUES)
    contracts.submit_for_review(UUID(cid), "ana")
    seeder.event(cid, "ana", "Enviaste el borrador a revisión humana.")
    contracts.review(UUID(cid), False, "bruno", "La modalidad no corresponde a este puesto")
    seeder.event(cid, "bruno", "El revisor bruno rechazó el contrato. Comentario: «La modalidad no corresponde a este puesto»")
    seeder.register(cid, "ana", "Rechazado, cerrado (REJECTED)")

    # 8. Devuelto para cambios
    cid = seeder.contract("ana", "")
    seeder.say(cid, "ana", FULL_MESSAGE, FULL_VALUES)
    contracts.submit_for_review(UUID(cid), "ana")
    seeder.event(cid, "ana", "Enviaste el borrador a revisión humana.")
    contracts.request_changes(UUID(cid), "bruno", "Falta aclarar el lugar de trabajo")
    seeder.event(cid, "bruno", "El revisor bruno pidió cambios en el borrador. Comentario: «Falta aclarar el lugar de trabajo»")
    seeder.register(cid, "ana", "Devuelto por el revisor con un comentario (COLLECTING_DATA)")

    # 9. De otro solicitante (para probar la visibilidad)
    cid = seeder.contract("carlos", "")
    seeder.say(cid, "carlos", "El empleado es Juan Pérez, DNI 30.123.456.", {k: v for k, v in EMPLOYEE_VALUES.items() if k in ("employee.nombre", "employee.apellido", "employee.dni")})
    seeder.register(cid, "carlos", "Contrato de carlos: ana no debe verlo (COLLECTING_DATA)")

    env_file = directory / "demo.env"
    entries = [
        {"name": n, "role": r, "key_sha256": hash_api_key(k)} for n, (r, k) in DEMO_USERS.items()
    ]
    env_file.write_text(
        "\n".join(
            [
                f"HUMANIA_DATABASE_PATH={settings.database_path}",
                f"HUMANIA_OUTPUT_DIR={settings.output_dir}",
                f"HUMANIA_ATTACHMENTS_DIR={settings.attachments_dir}",
                f"HUMANIA_CHROMA_PATH={settings.chroma_path}",
                f"HUMANIA_KNOWLEDGE_DIR={settings.knowledge_dir}",
                f"HUMANIA_API_USERS='{json.dumps(entries)}'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return DemoInfo(directory, env_file, seeder.created)
