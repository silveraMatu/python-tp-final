from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.contract import (
    CompanyData,
    ContractData,
    EmployeeData,
    EmploymentType,
    LaborTerms,
)

VALID_CUIL = "20-30123456-3"  # DNI 30123456
VALID_CUIT = "30-71234567-1"


@pytest.fixture
def employee() -> EmployeeData:
    return EmployeeData(
        nombre="Juan",
        apellido="Pérez",
        dni="30123456",
        cuil=VALID_CUIL,
        domicilio="Calle Falsa 742, Ciudad de Córdoba, Córdoba",
        fecha_nacimiento=date(1995, 3, 15),
    )


@pytest.fixture
def company() -> CompanyData:
    return CompanyData(
        razon_social="HumanIA S.A.",
        cuit=VALID_CUIT,
        domicilio_legal="Av. Ejemplo 1234, Ciudad de Córdoba, Córdoba",
        apoderado_nombre="María Gómez",
        apoderado_cargo="Gerente de RR. HH.",
    )


@pytest.fixture
def terms() -> LaborTerms:
    return LaborTerms(
        puesto_funcion="Desarrollador de Software",
        fecha_inicio=date(2026, 11, 9),
        modalidad=EmploymentType.INDETERMINATE,
        remuneracion_bruta=Decimal("2500000"),
        jornada_laboral="de lunes a viernes, de 9:00 a 17:00 hs (40 horas semanales)",
        lugar_trabajo="las oficinas de HumanIA S.A., Av. Ejemplo 1234, Córdoba",
    )


@pytest.fixture
def contract(employee: EmployeeData, company: CompanyData, terms: LaborTerms) -> ContractData:
    return ContractData(employee=employee, company=company, terms=terms)
