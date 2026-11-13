from __future__ import annotations

import pytest

from app.services.normalization import normalize_value


@pytest.mark.parametrize(
    ("path", "raw", "expected"),
    [
        ("employee.fecha_nacimiento", "15/03/1995", "1995-03-15"),
        ("employee.fecha_nacimiento", "15-3-1995", "1995-03-15"),
        ("terms.fecha_inicio", "9 de noviembre de 2026", "2026-11-09"),
        ("terms.fecha_inicio", "1995-3-5", "1995-03-05"),
        ("employee.fecha_nacimiento", "15 MAR 1995", "1995-03-15"),
        ("employee.fecha_nacimiento", "15 MAR/MAR 1995", "1995-03-15"),
        ("employee.fecha_nacimiento", "7 ENE / JAN 1990", "1990-01-07"),
        ("employee.fecha_nacimiento", "3 sept. 1988", "1988-09-03"),
        ("employee.fecha_nacimiento", "15 XYZ 1995", "15 XYZ 1995"),
        ("employee.fecha_nacimiento", "31 FEB 1995", "31 FEB 1995"),
        ("terms.fecha_inicio", "31/02/2026", "31/02/2026"),  # inválida: no se adivina
        ("terms.fecha_inicio", "pronto", "pronto"),
        ("terms.remuneracion_bruta", "$ 2.500.000", "2500000"),
        ("terms.remuneracion_bruta", "$2.500.000,50", "2500000.50"),
        ("terms.remuneracion_bruta", "2500000.50", "2500000.50"),
        ("terms.remuneracion_bruta", "2,5", "2.5"),
        ("terms.remuneracion_bruta", "ARS 1.500.000 pesos", "1500000"),
        ("terms.remuneracion_bruta", "mucha plata", "mucha plata"),
        ("terms.modalidad", "Contrato por tiempo indeterminado", "INDETERMINATE"),
        ("terms.modalidad", "a plazo fijo", "FIXED_TERM"),
        ("terms.modalidad", "Período de prueba", "TRIAL_PERIOD"),
        ("terms.modalidad", "tiempo parcial", "PART_TIME"),
        ("terms.modalidad", "part_time", "PART_TIME"),
        ("terms.modalidad", "fixed_term", "FIXED_TERM"),
        ("employee.dni", "DNI 30.123.456", "30123456"),
        ("employee.dni", "123", "123"),
        ("employee.cuil", "20-30123456-3", "20301234563"),
        ("employee.nombre", "  Juan   Carlos ", "Juan Carlos"),
    ],
)
def test_normalize_value(path: str, raw: str, expected: str) -> None:
    assert normalize_value(path, raw) == expected
