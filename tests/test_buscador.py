"""Buscador en lenguaje natural (4.4): interpretación, ordenamiento y API /buscar.
La IA se simula; las pruebas con base se saltan si no hay base disponible."""

import json
from decimal import Decimal

import pytest

from core.ia.catalogo import Atributo
from core.ia.interpretacion import Criterios, resumen_legible, validar_criterios
from core.ia.proveedores import ClienteIA, ErrorProveedor, LimiteExcedido, RespuestaModelo

CATALOGO = [
    Atributo(1, "acepta_mascotas", "Acepta mascotas", "booleano", "..."),
    Atributo(2, "gastos_comunes_clp", "Gastos comunes (CLP)", "numero", "..."),
    Atributo(3, "estacion_metro", "Estación de metro cercana", "texto", "..."),
]
COMUNAS = {"nunoa": "nunoa", "providencia": "providencia", "santiago": "santiago"}


# --------------------------------------------------------------------------- sin base
def test_validar_criterios_completo():
    datos = {
        "operacion": "arriendo", "tipo_propiedad": "departamento",
        "comunas": ["Ñuñoa", "Narnia"], "precio_max": "600.000", "moneda": "CLP",
        "dormitorios_min": 2, "banos_min": "1",
        "atributos": {"acepta_mascotas": True, "piscina": True,
                      "gastos_comunes_clp": 80000, "estacion_metro": None},
    }
    c, ignorado = validar_criterios(datos, CATALOGO, COMUNAS)
    assert c.comunas == ["nunoa"] and c.precio_max == Decimal("600000")
    assert c.dormitorios_min == 2 and c.banos_min == 1 and c.tipo_propiedad == "departamento"
    assert c.atributos == {"acepta_mascotas": True, "gastos_comunes_clp": Decimal("80000")}
    assert "comuna desconocida: Narnia" in ignorado
    assert "atributo desconocido: piscina" in ignorado


def test_validar_criterios_corrige_rangos_y_valores_raros():
    c, _ = validar_criterios(
        {"precio_min": 900000, "precio_max": 500000, "dormitorios_min": 99,
         "operacion": "permuta", "moneda": "uf"},
        CATALOGO, COMUNAS,
    )
    assert (c.precio_min, c.precio_max) == (500000, 900000)
    assert c.dormitorios_min is None and c.operacion is None and c.moneda == "UF"


def test_criterios_ida_y_vuelta_json():
    c = Criterios(comunas=["nunoa"], precio_max=Decimal("20.5"), moneda="UF",
                  atributos={"acepta_mascotas": True, "gastos_comunes_clp": Decimal("80000")})
    assert Criterios.desde_json(json.loads(json.dumps(c.a_json()))) == c


def test_resumen_legible():
    c = Criterios(operacion="arriendo", tipo_propiedad="departamento", comunas=["nunoa"],
                  precio_max=Decimal("600000"), dormitorios_min=2,
                  atributos={"acepta_mascotas": True, "gastos_comunes_clp": Decimal("80000")})
    partes = resumen_legible(c, {"acepta_mascotas": "Acepta mascotas"}, {"nunoa": "Ñuñoa"})
    assert partes == ["Departamento", "en arriendo", "Ñuñoa", "2+ dormitorios",
                      "hasta $600.000", "Acepta mascotas", "gastos comunes hasta $80.000"]


def test_cliente_respeta_el_tiempo_total():
    class Lento:
        nombre, modelo = "lento", "x"

        def completar(self, s, u):
            raise ErrorProveedor("sin respuesta a tiempo", reintentable=True)

    class NoDebeLlamarse:
        nombre, modelo = "otro", "x"

        def completar(self, s, u):
            pytest.fail("se pasó del tiempo total")

    reloj = iter([0.0, 0.0, 2.1])  # inicio, antes del 1°, antes del 2° (sin tiempo)
    import core.ia.proveedores as prov

    original = prov.time.monotonic
    prov.time.monotonic = lambda: next(reloj)
    try:
        with pytest.raises(ErrorProveedor, match="sin tiempo"):
            ClienteIA([Lento(), NoDebeLlamarse()], rondas=1, tiempo_total=2.2).completar("s", "u")
    finally:
        prov.time.monotonic = original


# --------------------------------------------------------------------------- con base
try:
    from core.db import conectar

    with conectar() as _c:
        _c.execute("SELECT 1 FROM atributo LIMIT 1")
    HAY_BASE = True
except Exception:  # noqa: BLE001
    HAY_BASE = False

con_base = pytest.mark.skipif(not HAY_BASE, reason="sin base de datos disponible")
PREFIJO = "test-busq-"


class IAFalsa:
    """Interpreta como lo haría el modelo, para unas pocas frases conocidas."""

    nombre, modelo = "falsa", "m"

    def __init__(self, fallar=False):
        self.llamadas = 0
        self.fallar = fallar

    def completar(self, sistema, usuario):
        self.llamadas += 1
        if self.fallar:
            raise LimiteExcedido("límite", 30)
        texto = usuario.lower()
        datos = {"operacion": "arriendo", "atributos": {}}
        if "ñuñoa" in texto:
            datos["comunas"] = ["Ñuñoa"]
        if "perro" in texto:
            datos["atributos"]["acepta_mascotas"] = True
        if "600 mil" in texto:
            datos["precio_max"] = 600000
        return RespuestaModelo(json.dumps(datos), self.nombre, self.modelo, 100, 30)


@pytest.fixture
def base():
    from core.ia.catalogo import cargar_catalogo

    with conectar(autocommit=True) as c:
        _limpiar(c)
        portal = c.execute("SELECT id FROM portal WHERE codigo = 'yapo'").fetchone()["id"]
        nunoa = c.execute("SELECT id FROM comuna WHERE slug = 'nunoa'").fetchone()["id"]
        provi = c.execute("SELECT id FROM comuna WHERE slug = 'providencia'").fetchone()["id"]
        cat = {a.codigo: a.id for a in cargar_catalogo(c)}
        avisos = {
            # clave: (comuna, precio, acepta_mascotas según la IA, confianza, días de antigüedad)
            "si_mascotas": (nunoa, 550000, True, 0.9, 10),
            "sin_dato": (nunoa, 500000, None, None, 1),
            "no_mascotas": (nunoa, 520000, False, 0.9, 1),
            "caro": (nunoa, 900000, True, 0.9, 1),
            "otra_comuna": (provi, 450000, True, 0.9, 1),
        }
        ids = {}
        for clave, (comuna, precio, mascotas, conf, dias) in avisos.items():
            pid = c.execute(
                """
                INSERT INTO publicacion (portal_id, id_externo, url, operacion, tipo_propiedad,
                    titulo, descripcion, precio_monto, precio_moneda, precio_clp, comuna_id,
                    dormitorios, hash_contenido, fecha_publicacion)
                VALUES (%s, %s, %s, 'arriendo', 'departamento', %s, %s, %s, 'CLP', %s, %s, 2,
                        'x', current_date - %s)
                RETURNING id
                """,
                (portal, PREFIJO + clave, f"https://ejemplo.cl/{clave}", f"Depto {clave}",
                 f"Departamento de prueba {clave}, cerca de parques y perros felices",
                 precio, precio, comuna, dias),
            ).fetchone()["id"]
            ids[clave] = pid
            if mascotas is not None:
                ext = c.execute(
                    "INSERT INTO extraccion_ia (publicacion_id, modelo, version_prompt, "
                    "hash_entrada, exitosa) VALUES (%s, 'm', 'v', 'h', true) RETURNING id",
                    (pid,),
                ).fetchone()["id"]
                c.execute(
                    "INSERT INTO publicacion_atributo (publicacion_id, atributo_id, fuente, "
                    "valor_bool, confianza, evidencia, extraccion_id) "
                    "VALUES (%s, %s, 'ia', %s, %s, 'texto', %s)",
                    (pid, cat["acepta_mascotas"], mascotas, conf, ext),
                )
        c.ids = ids
        yield c
        _limpiar(c)


def _limpiar(c):
    c.execute("DELETE FROM busqueda WHERE texto LIKE 'prueba-busq%'")
    c.execute("DELETE FROM publicacion WHERE id_externo LIKE %s", (PREFIJO + "%",))


def _solo_prueba(resultados, base):
    propios = set(base.ids.values())
    inverso = {v: k for k, v in base.ids.items()}
    return [inverso[r["id"]] for r in resultados if r["id"] in propios]


@con_base
def test_ordena_por_atributos_y_excluye_contradicciones(base):
    from core.buscador import buscar
    from core.ia.catalogo import cargar_catalogo

    c = Criterios(comunas=["nunoa"], precio_max=Decimal("600000"),
                  atributos={"acepta_mascotas": True})
    pagina = buscar(base, c, cargar_catalogo(base))
    orden = _solo_prueba(pagina.resultados, base)
    # el que confirma mascotas va primero aunque sea más antiguo; el que las prohíbe no aparece;
    # el caro y el de otra comuna quedan fuera por los filtros
    assert orden == ["si_mascotas", "sin_dato"]
    assert pagina.resultados[0]["coincidencias"] == ["acepta_mascotas"]


@con_base
def test_respaldo_por_palabras(base):
    from core.buscador import buscar
    from core.ia.catalogo import cargar_catalogo

    pagina = buscar(base, Criterios(), cargar_catalogo(base), texto_respaldo="perros felices")
    assert set(_solo_prueba(pagina.resultados, base)) >= {"si_mascotas", "sin_dato"}


@con_base
def test_api_buscar_interpreta_guarda_y_usa_cache(base, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as api

    ia = IAFalsa()
    monkeypatch.setattr(api, "cliente_busqueda", lambda: ClienteIA([ia], rondas=1))
    cliente = TestClient(api.app)
    texto = "prueba-busq depto en Ñuñoa que acepte perros bajo 600 mil"

    r = cliente.get("/buscar", params={"q": texto})
    assert r.status_code == 200
    datos = r.json()
    assert datos["interpretacion"]["interpretado"] is True
    assert "Ñuñoa" in datos["interpretacion"]["resumen"]
    assert _solo_prueba(datos["resultados"], base)[:2] == ["si_mascotas", "sin_dato"]
    primero = next(x for x in datos["resultados"] if x["id"] == base.ids["si_mascotas"])
    assert primero["atributos"][0]["codigo"] == "acepta_mascotas"

    fila = base.execute("SELECT criterios, n_resultados FROM busqueda WHERE id = %s",
                        (datos["busqueda_id"],)).fetchone()
    assert fila["criterios"]["_ia"]["comunas"] == ["nunoa"]
    n_guardados = base.execute(
        "SELECT count(*) AS n FROM resultado_busqueda WHERE busqueda_id = %s",
        (datos["busqueda_id"],),
    ).fetchone()["n"]
    assert n_guardados == len(datos["resultados"])

    # Misma búsqueda: sale de la caché, sin llamar de nuevo a la IA
    r2 = cliente.get("/buscar", params={"q": texto})
    assert r2.json()["interpretacion"]["desde_cache"] is True and ia.llamadas == 1

    # El filtro de la pantalla manda sobre el texto
    r3 = cliente.get("/buscar", params={"q": texto, "comuna": "providencia"})
    assert _solo_prueba(r3.json()["resultados"], base) == ["otra_comuna"]


@con_base
def test_api_buscar_sin_ia_busca_por_palabras(base, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as api

    monkeypatch.setattr(api, "cliente_busqueda", lambda: ClienteIA([IAFalsa(fallar=True)],
                                                                   rondas=1))
    datos = TestClient(api.app).get("/buscar", params={"q": "prueba-busq perros felices"}).json()
    assert datos["interpretacion"]["interpretado"] is False
    assert "palabras" in datos["interpretacion"]["aviso"]
    assert "si_mascotas" in _solo_prueba(datos["resultados"], base)


@con_base
def test_api_atributos_y_detalle(base):
    from fastapi.testclient import TestClient

    import api.main as api

    cliente = TestClient(api.app)
    codigos = {a["codigo"] for a in cliente.get("/atributos").json()}
    assert {"acepta_mascotas", "cerca_metro"} <= codigos
    detalle = cliente.get(f"/publicaciones/{base.ids['no_mascotas']}").json()
    assert detalle["atributos"][0]["valor"] is False
