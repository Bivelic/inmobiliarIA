from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.modelos import AvisoNormalizado
from core.normalizacion import a_clp, entero, moneda_de, numero, slug

AVISO = {
    "portal": "chilepropiedades",
    "id_externo": "137904440",
    "url": "https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/nunoa/departamento/x/137904440",
    "operacion": "arriendo",
    "tipo_propiedad": "departamento",
    "titulo": "Ñuñoa Departamento 2D, 2B, Metro L5",
    "descripcion": "Contactar al 9 8765 4321. Acepta mascotas.",
    "precio_monto": "580000",
    "precio_moneda": "CLP",
    "comuna": "Ñuñoa",
    "dormitorios": 2,
    "banos": 2,
    "m2_total": 55,
}


def test_aviso_valido_y_limpio():
    a = AvisoNormalizado(**AVISO)
    assert a.descripcion == "Contactar al [telefono]. Acepta mascotas."
    assert len(a.hash_contenido()) == 64


def test_hash_cambia_si_cambia_el_precio():
    a = AvisoNormalizado(**AVISO)
    b = AvisoNormalizado(**{**AVISO, "precio_monto": "600000"})
    assert a.hash_contenido() != b.hash_contenido()


@pytest.mark.parametrize(
    "cambio",
    [
        {"precio_monto": 0},
        {"portal": "otro"},
        {"url": "no-es-url"},
        {"dormitorios": 99},
        {"campo_extra": 1},
    ],
)
def test_aviso_invalido(cambio):
    with pytest.raises(ValidationError):
        AvisoNormalizado(**{**AVISO, **cambio})


def test_normalizacion():
    assert slug("Ñuñoa") == "nunoa"
    assert slug("Las Condes") == "las-condes"
    assert numero("$ 580.000") == Decimal("580000")
    assert numero("UF 14,13") == Decimal("14.13")
    assert entero("Habitaciones: 2") == 2
    assert moneda_de("UF 25") == "UF"
    assert a_clp(Decimal("10"), "UF", Decimal("39000")) == Decimal("390000")
    assert a_clp(Decimal("10"), "UF", None) is None
