"""API de InmobiliarIA (FastAPI). Solo lee la base: los scrapers son los que escriben.

Correr en local (desde la raíz, con el entorno virtual activo):
    uvicorn api.main:app --reload
Documentación interactiva: http://localhost:8000/docs
"""

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from core.config import cors_origins
from core.db import conectar

app = FastAPI(title="InmobiliarIA API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Regla 2.1.3: se muestra un extracto de la descripción, nunca el texto completo ni fotos;
# el detalle completo se ve en el aviso original (campo url).
LARGO_EXTRACTO = 280

CAMPOS = f"""
    p.id, po.codigo AS portal, p.url, p.operacion, p.tipo_propiedad, p.titulo,
    left(p.descripcion, {LARGO_EXTRACTO}) AS extracto,
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
    return {"total": total, "resultados": filas}


@app.get("/publicaciones/{publicacion_id}")
def detalle_publicacion(publicacion_id: int):
    with conectar() as conn:
        fila = conn.execute(
            f"SELECT {CAMPOS} {DESDE} WHERE p.id = %s", (publicacion_id,)
        ).fetchone()
    if not fila:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    return fila


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
