"""API de InmobiliarIA (FastAPI). Solo lee la base: los scrapers son los que escriben.

Correr en local (desde la raíz, con el entorno virtual activo):
    uvicorn api.main:app --reload
Documentación interactiva: http://localhost:8000/docs
"""

import time
import uuid
from datetime import date, timedelta
from functools import lru_cache
from typing import Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.leads import LeadSinPublicacion, guardar_lead_sin_publicacion
from api.leads import router as leads_router
from core.buscador import atributos_de, buscar, guardar_busqueda, guardar_resultados
from core.config import cors_origins
from core.db import conectar
from core.extracto import extracto_publico
from core.ia.catalogo import cargar_catalogo
from core.ia.interpretacion import (
    Criterios,
    criterios_para_guardar,
    interpretar,
    resumen_legible,
    version,
)
from core.ia.proveedores import ClienteIA, crear_proveedores
from core.leads import SolicitudContacto, guardar_lead, notificar, resumen_leads

app = FastAPI(title="InmobiliarIA API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)
app.include_router(leads_router)

# Regla 2.1.3: se muestra un extracto de la descripción, nunca el texto completo ni fotos;
# el detalle completo se ve en el aviso original (campo url).
CAMPOS = """
    p.id, po.codigo AS portal, p.url, p.operacion, p.tipo_propiedad, p.titulo,
    p.descripcion,
    p.precio_clp, p.precio_uf, p.gastos_comunes_clp,
    c.nombre AS comuna, c.slug AS comuna_slug,
    p.dormitorios, p.banos, p.m2_util, p.m2_total, p.estacionamientos,
    p.fecha_publicacion, p.ultima_vez_visto
"""
DESDE = """
    FROM publicacion p
    JOIN portal po ON po.id = p.portal_id
    LEFT JOIN comuna c ON c.id = p.comuna_id
"""

# Órdenes permitidos. El id al final deja el orden estable entre páginas ("Cargar más").
ORDENES = {
    "recientes": "p.fecha_publicacion DESC NULLS LAST, p.primera_vez_visto DESC, p.id DESC",
    "precio_asc": "p.precio_clp ASC NULLS LAST, p.id DESC",
    "precio_desc": "p.precio_clp DESC NULLS LAST, p.id DESC",
}


@app.get("/health")
def health():
    """Verifica que la API esté arriba y conectada a la base."""
    with conectar() as conn:
        conn.execute("SELECT 1")
    return {"estado": "ok"}


@app.get("/publicaciones")
def listar_publicaciones(
    operacion: Literal["arriendo", "venta"] = "arriendo",
    comuna: str | None = Query(None, description="slug de la comuna, ej. 'nunoa'"),
    precio_max: int | None = Query(None, ge=0, description="precio máximo en CLP"),
    dormitorios_min: int | None = Query(None, ge=0),
    orden: Literal["recientes", "precio_asc", "precio_desc"] = "recientes",
    limite: int = Query(20, ge=1, le=100),
    desde: int = Query(0, ge=0, description="cuántos resultados saltar (para 'Cargar más')"),
):
    """Avisos activos y no duplicados, con filtros tradicionales, orden y paginación."""
    condiciones = ["p.activa", "p.duplicado_de IS NULL", "p.operacion = %(operacion)s"]
    params: dict = {"operacion": operacion, "limite": limite, "desde": desde}
    if comuna:
        condiciones.append("c.slug = %(comuna)s")
        params["comuna"] = comuna
    if precio_max is not None:
        condiciones.append("p.precio_clp <= %(precio_max)s")
        params["precio_max"] = precio_max
    if dormitorios_min is not None:
        condiciones.append("p.dormitorios >= %(dormitorios_min)s")
        params["dormitorios_min"] = dormitorios_min

    donde = " AND ".join(condiciones)
    with conectar() as conn:
        total = conn.execute(f"SELECT count(*) AS n {DESDE} WHERE {donde}", params).fetchone()["n"]
        filas = conn.execute(
            f"SELECT {CAMPOS} {DESDE} WHERE {donde} "
            f"ORDER BY {ORDENES[orden]} LIMIT %(limite)s OFFSET %(desde)s",
            params,
        ).fetchall()
    for fila in filas:
        fila["extracto"] = extracto_publico(fila.pop("descripcion"))
    return {"total": total, "resultados": filas}


@app.get("/publicaciones/{publicacion_id}")
def detalle_publicacion(publicacion_id: int):
    with conectar() as conn:
        fila = conn.execute(
            f"SELECT {CAMPOS} {DESDE} WHERE p.id = %s", (publicacion_id,)
        ).fetchone()
        if not fila:
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        fila["atributos"] = atributos_de(conn, [publicacion_id])[publicacion_id]
    fila["extracto"] = extracto_publico(fila.pop("descripcion"))
    return fila


# --------------------------------------------------------------------------- búsqueda (4.4)
# Tiempo máximo (en total, sumando proveedores) para que la IA interprete el texto; si no
# alcanza, se busca por palabras. Así la búsqueda responde en menos de 3 s (RNF-06).
TIEMPO_MAXIMO_IA = 2.2


@lru_cache(maxsize=1)
def cliente_busqueda() -> ClienteIA | None:
    """Cliente de IA para interpretar búsquedas. None si no hay claves configuradas."""
    try:
        http = httpx.Client(timeout=TIEMPO_MAXIMO_IA)
        return ClienteIA(crear_proveedores(http=http), rondas=1, tiempo_total=TIEMPO_MAXIMO_IA)
    except RuntimeError:
        return None


def _uuid_o_none(texto: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(texto) if texto else None
    except ValueError:
        return None


def _catalogo(conn):
    try:
        return cargar_catalogo(conn)
    except RuntimeError:  # catálogo sin cargar (falta db/04_atributos.sql)
        return []


@app.get("/atributos")
def catalogo_atributos():
    """Atributos que detecta la IA (para mostrar etiquetas o filtros en la web)."""
    with conectar() as conn:
        return [
            {"codigo": a.codigo, "nombre": a.nombre, "tipo": a.tipo_dato}
            for a in _catalogo(conn)
        ]


@app.get("/buscar")
def buscar_publicaciones(
    q: str = Query("", max_length=300, description="búsqueda escrita, ej. 'depto en Ñuñoa "
                   "que acepte perros bajo 600 mil'"),
    comuna: str | None = Query(None, description="slug; si viene, reemplaza la del texto"),
    precio_max: int | None = Query(None, ge=0, description="CLP; reemplaza el del texto"),
    dormitorios_min: int | None = Query(None, ge=0),
    orden: Literal["relevancia", "recientes", "precio_asc", "precio_desc"] = "relevancia",
    limite: int = Query(20, ge=1, le=100),
    desde: int = Query(0, ge=0, description="para 'Cargar más'"),
    sesion: str | None = Query(None, max_length=36, description="uuid anónimo del navegador"),
    busqueda_id: int | None = Query(None, description="al pedir más resultados de una búsqueda"),
):
    """Búsqueda en lenguaje natural + filtros, ordenada por relevancia (RF-04, RF-05)."""
    inicio = time.perf_counter()
    with conectar() as conn:
        catalogo = _catalogo(conn)
        interpretacion = interpretar(conn, q, catalogo, cliente_busqueda()) if q.strip() else None
        criterios = interpretacion.criterios if interpretacion else Criterios()
        # Los filtros elegidos en pantalla mandan sobre lo que se entendió del texto (RF-04.04)
        if comuna:
            criterios.comunas = [comuna]
        if precio_max is not None:
            criterios.precio_max, criterios.moneda = precio_max, "CLP"
        if dormitorios_min is not None:
            criterios.dormitorios_min = dormitorios_min

        sin_ia = interpretacion is not None and not interpretacion.interpretado
        pagina = buscar(
            conn, criterios, catalogo,
            texto_respaldo=q if sin_ia else None,
            orden=orden, limite=limite, desde=desde,
        )
        ids = [r["id"] for r in pagina.resultados]
        atributos = atributos_de(conn, ids)
        for r in pagina.resultados:
            r["atributos"] = atributos.get(r["id"], [])

        duracion_ms = round((time.perf_counter() - inicio) * 1000)
        if desde == 0:
            busqueda_id = guardar_busqueda(
                conn, q.strip(), criterios_para_guardar(criterios, interpretacion, q,
                                                        version(catalogo)),
                pagina.total, duracion_ms, _uuid_o_none(sesion),
            )
        if busqueda_id is not None:
            guardar_resultados(conn, busqueda_id, pagina.resultados, desde)

        nombres_comunas = {
            f["slug"]: f["nombre"]
            for f in conn.execute(
                "SELECT slug, nombre FROM comuna WHERE slug = ANY(%s)", (criterios.comunas,)
            ).fetchall()
        }
    return {
        "busqueda_id": busqueda_id,
        "total": pagina.total,
        "duracion_ms": duracion_ms,
        "interpretacion": {
            "interpretado": interpretacion.interpretado if interpretacion else None,
            "desde_cache": interpretacion.desde_cache if interpretacion else False,
            "aviso": interpretacion.aviso if interpretacion else None,
            "resumen": resumen_legible(
                criterios, {a.codigo: a.nombre for a in catalogo}, nombres_comunas
            ),
            "criterios": criterios.a_json(),
        },
        "resultados": pagina.resultados,
    }


@app.get("/comunas")
def comunas_con_avisos():
    """Comunas que tienen al menos un aviso activo, para el filtro del frontend."""
    with conectar() as conn:
        return conn.execute(
            "SELECT c.slug, c.nombre, count(*) AS avisos FROM publicacion p "
            "JOIN comuna c ON c.id = p.comuna_id WHERE p.activa AND p.duplicado_de IS NULL "
            "GROUP BY c.slug, c.nombre ORDER BY c.nombre"
        ).fetchall()


@app.get("/metricas")
def metricas():
    """Avisos por portal y % sin error de la última ejecución (meta >= 95%)."""
    with conectar() as conn:
        return conn.execute(
            """
            SELECT po.codigo AS portal,
                   (SELECT count(*) FROM publicacion p
                     WHERE p.portal_id = po.id AND p.activa) AS avisos_activos,
                   u.inicio AS ultima_ejecucion, u.estado, u.avisos_leidos, u.avisos_ok,
                   round(100.0 * u.avisos_ok / NULLIF(u.avisos_leidos, 0), 1) AS pct_sin_error
            FROM portal po
            LEFT JOIN LATERAL (
                SELECT * FROM ejecucion_scraping e
                WHERE e.portal_id = po.id ORDER BY e.inicio DESC LIMIT 1
            ) u ON true
            WHERE po.activo
            ORDER BY po.id
            """
        ).fetchall()


# --------------------------------------------------------------------------- contacto (RF-07)
@app.post("/leads", status_code=201)
def crear_lead(solicitud: SolicitudContacto | LeadSinPublicacion, tareas: BackgroundTasks):
    """Registra una solicitud de contacto (con consentimiento) y avisa a Aurora por correo.
    El correo se envía después de responder, así el formulario no espera a Resend."""
    with conectar() as conn:
        if isinstance(solicitud, LeadSinPublicacion):
            return guardar_lead_sin_publicacion(conn, solicitud)
        lead = guardar_lead(conn, solicitud)
    if lead is None:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    tareas.add_task(notificar, lead)
    return {"id": lead["id"], "mensaje": "Solicitud registrada"}


@app.get("/metricas/leads")
def metricas_leads(desde: date | None = None, hasta: date | None = None):
    """Solicitudes de contacto y búsquedas en un período (por defecto, los últimos 30 días),
    para calcular la tasa de contactos por búsqueda (RF-07.05). Sin datos personales."""
    hasta = hasta or date.today() + timedelta(days=1)
    desde = desde or hasta - timedelta(days=30)
    with conectar() as conn:
        return resumen_leads(conn, desde, hasta)
