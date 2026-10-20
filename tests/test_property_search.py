"""Pruebas del adaptador que conecta property_search (código de Agustín) con nuestra base.
No hacen requests a ningún portal."""

from cargar_property_search import listing_a_aviso
from models.Listing import Listing  # de property_search

from core.modelos import AvisoNormalizado


def _listing(**cambios):
    base = dict(
        source="toctoc", listing_id="abc123",
        url="/propiedades/arriendo/departamento/nunoa/x/123",
        title="Depto 2D2B 55 m² útiles Ñuñoa", operation="Arriendo",
        property_type="Departamento", commune="Ñuñoa",
        price_uf=14.137, price_clp=580000, price_currency="CLP",
        area_m2=55, bedrooms=[2], bathrooms=[1, 2], lat=-33.45, lon=-70.6,
        broker="Corredora X", hours_published=30,
        description="Llamar al 9 8765 4321, acepta mascotas",
    )
    base.update(cambios)
    return Listing(**base)


def test_mapeo_completo_y_valido():
    datos = listing_a_aviso(_listing(), "https://www.toctoc.com")
    aviso = AvisoNormalizado(**datos)
    assert aviso.url.unicode_string().startswith("https://www.toctoc.com/propiedades/")
    assert aviso.operacion == "arriendo" and aviso.tipo_propiedad == "departamento"
    assert aviso.precio_moneda == "CLP" and aviso.precio_monto == 580000
    assert str(aviso.precio_uf) == "14.14"
    assert aviso.banos == 1  # proyecto con tipologías de 1 y 2 baños: se toma el menor
    assert aviso.m2_util == 55
    assert "[telefono]" in aviso.descripcion  # datos personales limpiados
    assert "broker" not in datos  # no se guarda el publicante


def test_aviso_en_uf():
    datos = listing_a_aviso(
        _listing(price_currency="UF", price_uf=25.0, price_clp=None), "https://www.toctoc.com"
    )
    aviso = AvisoNormalizado(**datos)
    assert aviso.precio_moneda == "UF" and aviso.precio_monto == 25


def test_sin_precio_no_pasa_la_validacion():
    datos = listing_a_aviso(_listing(price_uf=None, price_clp=None, price_currency=None))
    try:
        AvisoNormalizado(**datos)
    except Exception:
        return
    raise AssertionError("un aviso sin precio debería ser rechazado")
