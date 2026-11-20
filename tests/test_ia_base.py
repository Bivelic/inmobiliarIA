"""Extracción de punta a punta sobre la base, con un proveedor de IA simulado (sin claves).
Necesitan una base con el esquema y db/04_atributos.sql cargados; si no hay, se saltan."""

import json

import pytest

try:
    from core.db import conectar

    with conectar() as _c:
        _c.execute("SELECT 1 FROM atributo LIMIT 1")
    HAY_BASE = True
except Exception:  # noqa: BLE001
    HAY_BASE = False

pytestmark = pytest.mark.skipif(not HAY_BASE, reason="sin base de datos disponible")

from core.ia.catalogo import cargar_catalogo  # noqa: E402
from core.ia.evaluacion import (  # noqa: E402
    comparar,
    guardar_etiquetas,
    leer_etiquetas,
    predicciones_ia,
    total,
)
from core.ia.extraccion import Extractor, avisos_pendientes  # noqa: E402
from core.ia.proveedores import ClienteIA, ErrorProveedor, RespuestaModelo  # noqa: E402

PREFIJO = "test-ia-"
TEXTOS = {
    "a": ("Depto 2D2B Ñuñoa", "Lindo depto, se aceptan mascotas. Gastos comunes $90.000. "
          "Edificio con piscina y gimnasio. A 3 cuadras del metro Ñuble."),
    "b": ("Depto Providencia", "No se aceptan mascotas. Incluye estacionamiento y bodega."),
    "c": ("Casa Maipú", "Casa amplia con patio, cerca de colegios y supermercados."),
}


class IAFalsa:
    """Responde según el texto del aviso, como lo haría un modelo bien portado."""

    nombre, modelo = "falsa", "modelo-falso"

    def __init__(self, fallar_en_llamada: int | None = None, inventar: bool = False):
        self.llamadas = 0
        self.fallar_en_llamada = fallar_en_llamada
        self.inventar = inventar

    def completar(self, sistema, usuario):
        self.llamadas += 1
        if self.llamadas == self.fallar_en_llamada:
            raise ErrorProveedor("cuota diaria agotada")
        avisos = json.loads(usuario.split("\n", 1)[1])
        salida = []
        for a in avisos:
            d = a["descripcion"]
            attrs = {}
            if "se aceptan mascotas" in d:
                negado = d.startswith("No se")
                attrs["acepta_mascotas"] = {
                    "valor": not negado,
                    "evidencia": "No se aceptan mascotas" if negado else "se aceptan mascotas",
                    "confianza": 0.9,
                }
            if "$90.000" in d:
                attrs["gastos_comunes_clp"] = {"valor": 90000,
                                               "evidencia": "Gastos comunes $90.000"}
            if "metro Ñuble" in d:
                attrs["cerca_metro"] = {"valor": True, "evidencia": "A 3 cuadras del metro Ñuble"}
                attrs["estacion_metro"] = {"valor": "Ñuble", "evidencia": "metro Ñuble"}
            if self.inventar:
                attrs["piscina"] = {"valor": True, "evidencia": "piscina temperada"}  # no está
            salida.append({"id": a["id"], "atributos": attrs})
        return RespuestaModelo(json.dumps({"avisos": salida}), self.nombre, self.modelo, 500, 100)


@pytest.fixture
def conn():
    with conectar(autocommit=True) as c:
        _limpiar(c)
        portal = c.execute("SELECT id FROM portal WHERE codigo = 'yapo'").fetchone()["id"]
        ids = {}
        for clave, (titulo, descripcion) in TEXTOS.items():
            ids[clave] = c.execute(
                """
                INSERT INTO publicacion (portal_id, id_externo, url, operacion, tipo_propiedad,
                    titulo, descripcion, precio_monto, precio_moneda, hash_contenido)
                VALUES (%s, %s, %s, 'arriendo', 'departamento', %s, %s, 500000, 'CLP', 'x')
                RETURNING id
                """,
                (portal, PREFIJO + clave, f"https://ejemplo.cl/{clave}", titulo, descripcion),
            ).fetchone()["id"]
        c.ids = ids
        yield c
        _limpiar(c)


def _limpiar(c):
    c.execute("DELETE FROM publicacion WHERE id_externo LIKE %s", (PREFIJO + "%",))


def _atributos(c, pid):
    filas = c.execute(
        "SELECT a.codigo, pa.valor_bool, pa.valor_num, pa.valor_texto, pa.evidencia "
        "FROM publicacion_atributo pa JOIN atributo a ON a.id = pa.atributo_id "
        "WHERE pa.publicacion_id = %s AND pa.fuente = 'ia'",
        (pid,),
    ).fetchall()
    return {f["codigo"]: f for f in filas}


def _extractor(c, ia):
    return Extractor(c, ClienteIA([ia], dormir=lambda s: None), pausa=0)


def test_extrae_guarda_y_no_repite(conn):
    ids = list(conn.ids.values())
    ia = IAFalsa()
    r = _extractor(conn, ia).correr(ids=ids, tamano_lote=2)
    assert (r.pendientes, r.exitosos, r.fallidos, r.llamadas) == (3, 3, 0, 2)

    a = _atributos(conn, conn.ids["a"])
    assert a["acepta_mascotas"]["valor_bool"] is True
    assert a["gastos_comunes_clp"]["valor_num"] == 90000
    assert a["estacion_metro"]["valor_texto"] == "Ñuble"
    assert _atributos(conn, conn.ids["b"])["acepta_mascotas"]["valor_bool"] is False
    assert _atributos(conn, conn.ids["c"]) == {}  # no menciona nada del catálogo

    fila = conn.execute(
        "SELECT modelo, exitosa, tokens_entrada FROM extraccion_ia WHERE publicacion_id = %s",
        (conn.ids["a"],),
    ).fetchone()
    assert fila["modelo"] == "falsa:modelo-falso" and fila["exitosa"]

    # Segunda corrida: nada pendiente, no se llama a la IA
    ia2 = IAFalsa()
    r2 = _extractor(conn, ia2).correr(ids=ids)
    assert r2.pendientes == 0 and ia2.llamadas == 0


def test_reprocesa_si_cambia_el_texto(conn):
    ids = list(conn.ids.values())
    _extractor(conn, IAFalsa()).correr(ids=ids)
    conn.execute(
        "UPDATE publicacion SET descripcion = 'No se aceptan mascotas. Sin bodega.' WHERE id = %s",
        (conn.ids["a"],),
    )
    r = _extractor(conn, IAFalsa()).correr(ids=ids)
    assert r.pendientes == 1
    a = _atributos(conn, conn.ids["a"])
    assert set(a) == {"acepta_mascotas"} and a["acepta_mascotas"]["valor_bool"] is False


def test_descarta_lo_inventado(conn):
    r = _extractor(conn, IAFalsa(inventar=True)).correr(ids=[conn.ids["c"]])
    assert r.exitosos == 1 and r.descartados == 1
    assert _atributos(conn, conn.ids["c"]) == {}


def test_se_detiene_si_la_ia_no_responde_y_guarda_lo_anterior(conn):
    ids = list(conn.ids.values())
    r = _extractor(conn, IAFalsa(fallar_en_llamada=2)).correr(ids=ids, tamano_lote=1)
    assert r.exitosos == 1 and r.detenido_por
    pendientes = avisos_pendientes(conn, r.version_prompt, 100, ids)
    assert len(pendientes) == 2  # los que faltaron quedan para la próxima corrida


def test_respuesta_rota_se_reintenta_de_a_uno(conn):
    class Rota(IAFalsa):
        def completar(self, sistema, usuario):
            n_avisos = len(json.loads(usuario.split("\n", 1)[1]))
            if n_avisos > 1:
                self.llamadas += 1
                return RespuestaModelo("no es json", self.nombre, self.modelo, 1, 1)
            return super().completar(sistema, usuario)

    ia = Rota()
    r = _extractor(conn, ia).correr(ids=list(conn.ids.values()), tamano_lote=3)
    assert r.exitosos == 3 and r.fallidos == 0 and ia.llamadas == 4


def test_evaluacion_contra_etiquetas(conn, tmp_path):
    ids = list(conn.ids.values())
    _extractor(conn, IAFalsa()).correr(ids=ids)
    catalogo = cargar_catalogo(conn)
    csv = tmp_path / "v.csv"
    csv.write_text(
        "publicacion_id;acepta_mascotas;gastos_comunes_clp;piscina;etiquetado_por\n"
        f"{conn.ids['a']};si;90000;si;QA\n"
        f"{conn.ids['b']};no;;;QA\n"
        f"{conn.ids['c']};;;;QA\n",
        encoding="utf-8-sig",
    )
    et = leer_etiquetas(csv, catalogo)
    m = comparar(et.valores, predicciones_ia(conn, ids), ids,
                 {a.codigo: a.tipo_dato for a in catalogo})
    t = total(m)
    assert t.precision == 1.0 and m["piscina"].omitidos == 1
    assert guardar_etiquetas(conn, et, catalogo) == 4
