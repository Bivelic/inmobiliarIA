"""Pruebas del spider de Chilepropiedades sobre fichas guardadas (sin red).

- chilepropiedades_real.html: ficha real descargada el 20/10/2026. Se lee desde el JSON-LD.
- chilepropiedades_ficha.html: ficha sintética SIN JSON-LD, para probar el respaldo por
  rótulos del HTML. Reproduce los errores del 20/10 (precio x UF, 0 dormitorios por leer
  el buscador, sin descripción).
"""

from pathlib import Path

import pytest
from inmobiliaria_scrapers.spiders.chilepropiedades import ChilepropiedadesSpider
from pydantic import ValidationError
from scrapy.http import HtmlResponse

from core.modelos import AvisoNormalizado
from core.normalizacion import numero, precio

FIXTURE = Path(__file__).parent / "fixtures" / "chilepropiedades_ficha.html"
URL = (
    "https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/la-florida/"
    "departamento/geronimo-de-alderete-400/140112233"
)


@pytest.fixture(scope="module")
def item():
    respuesta = HtmlResponse(url=URL, body=FIXTURE.read_bytes(), encoding="utf-8")
    return next(ChilepropiedadesSpider().parse_aviso(respuesta))


def test_precio_en_pesos_no_en_uf(item):
    assert item["precio_moneda"] == "CLP"
    assert item["precio_monto"] == 550000


def test_dormitorios_del_aviso_no_del_buscador(item):
    assert item["dormitorios"] == 2
    assert item["banos"] == 2
    assert item["estacionamientos"] == 1


def test_descripcion_completa_y_sin_el_siguiente_titulo(item):
    d = item["descripcion"]
    assert d.startswith("Departamento nuevo tipo mariposa")
    assert "Acepta mascotas" in d
    assert "Ver descripción completa" not in d
    assert "Ubicación" not in d


def test_resto_de_campos(item):
    assert float(item["m2_total"]) == 54.34
    assert item["m2_util"] == 50
    assert item["gastos_comunes_clp"] == 89000
    assert item["id_externo"] == "140112233"
    assert item["comuna"] == "la-florida"


def test_aviso_valido_y_sin_telefono(item):
    aviso = AvisoNormalizado(**item)
    assert "[telefono]" in aviso.descripcion


def test_precio_imposible_se_rechaza(item):
    with pytest.raises(ValidationError, match="precio fuera de rango"):
        AvisoNormalizado(**{**item, "precio_moneda": "UF"})  # 550.000 UF de arriendo


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Valor $ 550.000 Valor (UF aprox.)* UF 13,35", (550000, "CLP")),
        ("UF 25,5", (25.5, "UF")),
        ("US$ 1.200", (1200, "USD")),
        ("Incluye uso de bodega $ 300.000", (300000, "CLP")),
        ("sin precio", (None, None)),
    ],
)
def test_precio(texto, esperado):
    monto, moneda = precio(texto)
    assert (float(monto) if monto is not None else None, moneda) == esperado


@pytest.mark.parametrize(
    "texto, esperado",
    [("54,34 m²", 54.34), ("37.00 m²", 37.0), ("1.200 m2", 1200), ("$ 1.750.000", 1750000)],
)
def test_numero(texto, esperado):
    assert float(numero(texto)) == esperado


# ---------------------------------------------------------------- ficha real (JSON-LD)
FICHA_REAL = Path(__file__).parent / "fixtures" / "chilepropiedades_real.html"
URL_REAL = (
    "https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/la-florida/"
    "departamento/geronimo-de-alderete-400/143609473"
)


@pytest.fixture(scope="module")
def real():
    respuesta = HtmlResponse(url=URL_REAL, body=FICHA_REAL.read_bytes(), encoding="utf-8")
    return next(ChilepropiedadesSpider().parse_aviso(respuesta))


def test_real_valores_de_la_pagina(real):
    # Lo que muestra la página: $ 550.000, 2 habitaciones, 2 baños, 1 estac., 54,34 m²,
    # gastos comunes $ 89.000
    assert (real["precio_monto"], real["precio_moneda"]) == (550000, "CLP")
    assert (real["dormitorios"], real["banos"], real["estacionamientos"]) == (2, 2, 1)
    assert float(real["m2_total"]) == 54.34
    assert float(real["m2_util"]) == 47.15
    assert real["gastos_comunes_clp"] == 89000
    assert str(real["fecha_publicacion"]) == "2026-10-20"
    assert real["latitud"] is not None and real["longitud"] is not None


def test_real_descripcion_completa(real):
    d = real["descripcion"]
    assert d.startswith("Se arrienda cómodo departamento")
    assert "SOMOS TU COACH INMOBILIARIO" in d  # último párrafo: no viene recortada
    assert "Ver descripción completa" not in d


def test_real_es_un_aviso_valido(real):
    AvisoNormalizado(**real)
