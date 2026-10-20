import pytest

from core.limpieza import contiene_datos_personales, limpiar_datos_personales


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Escribir a juan.perez@gmail.com", "Escribir a [correo]"),
        ("Llamar al +56 9 1234 5678", "Llamar al [telefono]"),
        ("WhatsApp 912345678 horario oficina", "WhatsApp [telefono] horario oficina"),
        ("Fono (2) 2345 6789", "Fono [telefono]"),
        ("RUT 12.345.678-9 del dueño", "RUT [rut] del dueño"),
        ("Agente: Carolina Contreras. Visitas", "Agente: [nombre]. Visitas"),
    ],
)
def test_quita_datos_personales(texto, esperado):
    assert limpiar_datos_personales(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "Arriendo $580.000 + gastos comunes $96.000",
        "Valor $1.000.000 mensual",
        "UF 14,13 aprox., 55 m² totales",
        "Metro L5 a 3 cuadras, piso 15",
    ],
)
def test_no_toca_precios_ni_datos_de_la_propiedad(texto):
    assert limpiar_datos_personales(texto) == texto
    assert not contiene_datos_personales(texto)


def test_none_se_mantiene():
    assert limpiar_datos_personales(None) is None
