"""Panel de leads para ejecutivos de Aurora: login, listado, asignación, estados e indicadores.

Todas las rutas exigen sesión de ejecutivo, salvo POST /auth/login y POST /leads (el formulario público).
"""

from datetime import date, timedelta
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth import HASH_FALSO, crear_token, leer_token, verificar_password
from core.db import conectar

router = APIRouter()

Estado = Literal["nuevo", "contactado", "visita_agendada", "cerrado", "descartado"]
# Pasar a uno de estos estados por primera vez cuenta como "primera respuesta" de Aurora al cliente
ESTADOS_RESPUESTA = ("contactado", "visita_agendada", "cerrado")
EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
MAX_DIAS_PERIODO = 366
ZONA = "America/Santiago"  # los períodos se cuentan por día chileno, no por día UTC


def _rango(columna: str) -> str:
    """Condición SQL para filtrar `columna` entre %(desde)s y %(hasta)s (ambos días incluidos)."""
    return (
        f"{columna} >= (%(desde)s::date)::timestamp AT TIME ZONE '{ZONA}' "
        f"AND {columna} < ((%(hasta)s::date + 1)::timestamp AT TIME ZONE '{ZONA}')"
    )


# ---------------------------------------------------------------- sesión
def ejecutivo_actual(authorization: str | None = Header(default=None)) -> dict:
    esquema, _, token = (authorization or "").partition(" ")
    ejecutivo_id = leer_token(token.strip()) if esquema.lower() == "bearer" else None
    ejecutivo = None
    if ejecutivo_id is not None:
        with conectar() as conn:
            ejecutivo = conn.execute(
                "SELECT id, nombre, email FROM ejecutivo WHERE id = %s AND activo", (ejecutivo_id,)
            ).fetchone()
    if ejecutivo is None:
        raise HTTPException(401, "Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    return ejecutivo


class LoginEntrada(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/login")
def login(datos: LoginEntrada):
    with conectar() as conn:
        fila = conn.execute(
            "SELECT id, nombre, email, password_hash FROM ejecutivo WHERE email = lower(%s) AND activo",
            (datos.email.strip(),),
        ).fetchone()
    correcta = verificar_password(datos.password, fila["password_hash"] if fila else HASH_FALSO)
    if not fila or not correcta:
        raise HTTPException(401, "Correo o contraseña incorrectos")  # mismo mensaje en ambos casos
    return {
        "token": crear_token(fila["id"]),
        "ejecutivo": {"id": fila["id"], "nombre": fila["nombre"], "email": fila["email"]},
    }


@router.get("/auth/yo")
def quien_soy(yo: dict = Depends(ejecutivo_actual)):
    return yo


@router.get("/ejecutivos")
def listar_ejecutivos(yo: dict = Depends(ejecutivo_actual)):
    """Ejecutivos activos, para el selector de 'asignar a'."""
    with conectar() as conn:
        return conn.execute("SELECT id, nombre FROM ejecutivo WHERE activo ORDER BY nombre").fetchall()


# ---------------------------------------------------------------- formulario público
class LeadEntrada(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: str = Field(pattern=EMAIL_REGEX, max_length=200)
    telefono: str | None = Field(default=None, max_length=30)
    mensaje: str | None = Field(default=None, max_length=2000)
    consentimiento: bool
    publicacion_id: int | None = None


@router.post("/leads", status_code=201)
def crear_lead(datos: LeadEntrada):
    """Solicitud de contacto desde la web. Exige consentimiento (Ley 21.719) y no devuelve datos personales."""
    if not datos.consentimiento:
        raise HTTPException(422, "Se necesita el consentimiento para guardar tus datos")
    try:
        with conectar() as conn:
            fila = conn.execute(
                "INSERT INTO lead (publicacion_id, nombre, email, telefono, mensaje, consentimiento) "
                "VALUES (%s, %s, %s, %s, %s, true) RETURNING id",
                (datos.publicacion_id, datos.nombre.strip(), datos.email.strip().lower(),
                 (datos.telefono or "").strip() or None, (datos.mensaje or "").strip() or None),
            ).fetchone()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "La publicación indicada no existe")
    return {"id": fila["id"]}


# ---------------------------------------------------------------- panel
LEAD_SELECT = """
    SELECT l.id, l.nombre, l.email, l.telefono, l.mensaje, l.estado,
           l.ejecutivo_id, e.nombre AS ejecutivo_nombre,
           l.creado_en, l.primera_respuesta_en, l.visita_agendada_en,
           l.publicacion_id, p.titulo AS publicacion_titulo, p.url AS publicacion_url, po.codigo AS portal
    FROM lead l
    LEFT JOIN ejecutivo e ON e.id = l.ejecutivo_id
    LEFT JOIN publicacion p ON p.id = l.publicacion_id
    LEFT JOIN portal po ON po.id = p.portal_id
"""


@router.get("/leads")
def listar_leads(
    estado: Estado | None = None,
    ejecutivo_id: int | None = Query(None, description="solo los asignados a este ejecutivo"),
    sin_asignar: bool = False,
    fecha_desde: date | None = Query(None, description="recibidos desde este día (incluido)"),
    fecha_hasta: date | None = Query(None, description="recibidos hasta este día (incluido)"),
    limite: int = Query(30, ge=1, le=100),
    salto: int = Query(0, ge=0, description="cuántos resultados saltar (para 'Cargar más')"),
    yo: dict = Depends(ejecutivo_actual),
):
    if sin_asignar and ejecutivo_id is not None:
        raise HTTPException(422, "Usa sin_asignar o ejecutivo_id, no los dos")
    condiciones, params = ["true"], {"limite": limite, "salto": salto}
    if estado:
        condiciones.append("l.estado = %(estado)s")
        params["estado"] = estado
    if ejecutivo_id is not None:
        condiciones.append("l.ejecutivo_id = %(ejecutivo_id)s")
        params["ejecutivo_id"] = ejecutivo_id
    if sin_asignar:
        condiciones.append("l.ejecutivo_id IS NULL")
    if fecha_desde:
        condiciones.append(f"l.creado_en >= (%(fecha_desde)s::date)::timestamp AT TIME ZONE '{ZONA}'")
        params["fecha_desde"] = fecha_desde
    if fecha_hasta:
        condiciones.append(f"l.creado_en < ((%(fecha_hasta)s::date + 1)::timestamp AT TIME ZONE '{ZONA}')")
        params["fecha_hasta"] = fecha_hasta
    donde = " AND ".join(condiciones)
    with conectar() as conn:
        total = conn.execute(f"SELECT count(*) AS n FROM lead l WHERE {donde}", params).fetchone()["n"]
        filas = conn.execute(
            f"{LEAD_SELECT} WHERE {donde} ORDER BY l.creado_en DESC, l.id DESC LIMIT %(limite)s OFFSET %(salto)s",
            params,
        ).fetchall()
    return {"total": total, "resultados": filas}


class LeadCambio(BaseModel):
    estado: Estado | None = None
    ejecutivo_id: int | None = None  # null = dejar sin asignar


@router.patch("/leads/{lead_id}")
def actualizar_lead(lead_id: int, datos: LeadCambio, yo: dict = Depends(ejecutivo_actual)):
    """Cambia el estado y/o el ejecutivo asignado. Cada cambio queda en el historial (lead_evento)."""
    enviados = datos.model_fields_set
    if not enviados & {"estado", "ejecutivo_id"}:
        raise HTTPException(422, "Indica estado y/o ejecutivo_id")
    if "estado" in enviados and datos.estado is None:
        raise HTTPException(422, "El estado no puede ser null")

    with conectar() as conn:
        lead = conn.execute(
            "SELECT estado, ejecutivo_id, primera_respuesta_en, visita_agendada_en FROM lead WHERE id = %s FOR UPDATE",
            (lead_id,),
        ).fetchone()
        if lead is None:
            raise HTTPException(404, "Lead no encontrado")

        cambios, params, eventos = [], {"id": lead_id}, []
        if "estado" in enviados and datos.estado != lead["estado"]:
            cambios.append("estado = %(estado)s")
            params["estado"] = datos.estado
            # Las fechas son "la primera vez": volver atrás en el estado no las borra ni las pisa
            if datos.estado in ESTADOS_RESPUESTA and lead["primera_respuesta_en"] is None:
                cambios.append("primera_respuesta_en = now()")
            if datos.estado == "visita_agendada" and lead["visita_agendada_en"] is None:
                cambios.append("visita_agendada_en = now()")
            eventos.append(("estado", lead["estado"], datos.estado, None, None))
        if "ejecutivo_id" in enviados and datos.ejecutivo_id != lead["ejecutivo_id"]:
            if datos.ejecutivo_id is not None:
                existe = conn.execute(
                    "SELECT 1 FROM ejecutivo WHERE id = %s AND activo", (datos.ejecutivo_id,)
                ).fetchone()
                if not existe:
                    raise HTTPException(422, "El ejecutivo no existe o está inactivo")
            cambios.append("ejecutivo_id = %(ejecutivo_id)s")
            params["ejecutivo_id"] = datos.ejecutivo_id
            eventos.append(("asignacion", None, None, lead["ejecutivo_id"], datos.ejecutivo_id))

        if cambios:
            conn.execute(f"UPDATE lead SET {', '.join(cambios)}, actualizado_en = now() WHERE id = %(id)s", params)
            for tipo, est_ant, est_nuevo, asig_ant, asig_nuevo in eventos:
                conn.execute(
                    "INSERT INTO lead_evento (lead_id, ejecutivo_id, tipo, estado_anterior, estado_nuevo, "
                    "asignado_anterior_id, asignado_nuevo_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (lead_id, yo["id"], tipo, est_ant, est_nuevo, asig_ant, asig_nuevo),
                )
        return conn.execute(f"{LEAD_SELECT} WHERE l.id = %s", (lead_id,)).fetchone()


# ---------------------------------------------------------------- indicadores
def _metricas(conn, desde: date, hasta: date) -> dict:
    """Indicadores de los leads RECIBIDOS en el período (aunque la respuesta o la visita ocurran después)."""
    fila = conn.execute(
        f"""
        SELECT count(*) AS recibidas,
               count(*) FILTER (WHERE primera_respuesta_en IS NULL AND estado <> 'descartado') AS sin_respuesta,
               count(primera_respuesta_en) AS con_respuesta,
               percentile_cont(0.5) WITHIN GROUP
                   (ORDER BY (extract(epoch FROM primera_respuesta_en - creado_en) / 60)::float8) AS mediana_min,
               avg((extract(epoch FROM primera_respuesta_en - creado_en) / 60)::float8) AS promedio_min,
               count(visita_agendada_en) AS visitas
        FROM lead WHERE {_rango('creado_en')}
        """,
        {"desde": desde, "hasta": hasta},
    ).fetchone()
    recibidas, visitas = fila["recibidas"], fila["visitas"]
    redondear = lambda valor: None if valor is None else round(float(valor), 1)  # noqa: E731
    return {
        "recibidas": recibidas,
        "sin_respuesta": fila["sin_respuesta"],
        "con_respuesta": fila["con_respuesta"],
        "mediana_primera_respuesta_min": redondear(fila["mediana_min"]),
        "promedio_primera_respuesta_min": redondear(fila["promedio_min"]),
        "visitas_agendadas": visitas,
        "tasa_visitas_pct": round(100.0 * visitas / recibidas, 1) if recibidas else None,
    }


@router.get("/leads/indicadores")
def indicadores(
    desde: date | None = Query(None, description="primer día del período (por defecto, hace 30 días)"),
    hasta: date | None = Query(None, description="último día del período (por defecto, hoy en Chile)"),
    yo: dict = Depends(ejecutivo_actual),
):
    """Indicadores del período y del período anterior de igual largo, para medir el +20% del Caso de Negocio."""
    with conectar() as conn:
        hoy = conn.execute(f"SELECT (now() AT TIME ZONE '{ZONA}')::date AS hoy").fetchone()["hoy"]
        hasta = hasta or hoy
        desde = desde or hasta - timedelta(days=29)
        if desde > hasta:
            raise HTTPException(422, "desde no puede ser posterior a hasta")
        dias = (hasta - desde).days + 1
        if dias > MAX_DIAS_PERIODO:
            raise HTTPException(422, f"El período no puede superar {MAX_DIAS_PERIODO} días")
        anterior_hasta = desde - timedelta(days=1)
        anterior_desde = anterior_hasta - timedelta(days=dias - 1)
        return {
            "periodo": {"desde": desde, "hasta": hasta, "dias": dias, **_metricas(conn, desde, hasta)},
            "anterior": {"desde": anterior_desde, "hasta": anterior_hasta,
                         **_metricas(conn, anterior_desde, anterior_hasta)},
        }
