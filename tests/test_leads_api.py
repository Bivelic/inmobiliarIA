"""Pruebas del panel de leads con la migración db/04_leads_panel.sql cargada.

Todo lo que crean usa correos @test.invalid y se borra al terminar cada prueba.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "clave-solo-para-pruebas-" + "x" * 32)

from api.main import app  # noqa: E402
from core.auth import hashear_password  # noqa: E402
from core.db import conectar  # noqa: E402


def _hay_base() -> bool:
    try:
        with conectar() as conn:
            conn.execute("SELECT 1 FROM ejecutivo, lead_evento LIMIT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _hay_base(), reason="No hay base con la migración db/04_leads_panel.sql"
)

CLAVE = "clave-de-prueba-123"
SUFIJO = "@test.invalid"


@pytest.fixture(autouse=True)
def limpiar():
    yield
    with conectar() as conn:
        conn.execute("DELETE FROM lead WHERE email LIKE %s", ("%" + SUFIJO,))
        conn.execute("DELETE FROM ejecutivo WHERE email LIKE %s", ("%" + SUFIJO,))


@pytest.fixture
def cliente():
    return TestClient(app)


def _crear_ejecutivo(activo: bool = True) -> dict:
    email = f"{uuid.uuid4().hex[:10]}{SUFIJO}"
    with conectar() as conn:
        fila = conn.execute(
            "INSERT INTO ejecutivo (nombre, email, password_hash, activo) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            ("Ejecutiva de prueba", email, hashear_password(CLAVE), activo),
        ).fetchone()
    return {"id": fila["id"], "email": email}


def _entrar(cliente, ejecutivo: dict) -> dict:
    respuesta = cliente.post("/auth/login", json={"email": ejecutivo["email"], "password": CLAVE})
    assert respuesta.status_code == 200
    return {"Authorization": f"Bearer {respuesta.json()['token']}"}


@pytest.fixture
def sesion(cliente) -> dict:
    ejecutivo = _crear_ejecutivo()
    return {"id": ejecutivo["id"], "cabeceras": _entrar(cliente, ejecutivo)}


def _crear_lead(cliente, **extra) -> int:
    datos = {
        "nombre": "Cliente de prueba",
        "email": f"{uuid.uuid4().hex[:10]}{SUFIJO}",
        "consentimiento": True,
        **extra,
    }
    respuesta = cliente.post("/leads", json=datos)
    assert respuesta.status_code == 201
    return respuesta.json()["id"]


def _lead_con_fechas(
    creado_local: str, estado: str, minutos_respuesta=None, con_visita: bool = False
) -> None:
    """Crea un lead con fecha en hora de Chile para probar los indicadores."""
    with conectar() as conn:
        conn.execute(
            """
            WITH base AS (
                SELECT (%(creado)s::timestamp AT TIME ZONE 'America/Santiago') AS instante
            )
            INSERT INTO lead (nombre, email, consentimiento, estado, creado_en,
                              primera_respuesta_en, visita_agendada_en)
            SELECT 'Lead de prueba', %(email)s, true, %(estado)s::estado_lead_t, instante,
                   CASE WHEN %(minutos)s::int IS NULL THEN NULL
                        ELSE instante + make_interval(mins => %(minutos)s::int) END,
                   CASE WHEN %(visita)s::boolean THEN instante + interval '1 day' END
            FROM base
            """,
            {
                "creado": creado_local,
                "email": f"{uuid.uuid4().hex[:10]}{SUFIJO}",
                "estado": estado,
                "minutos": minutos_respuesta,
                "visita": con_visita,
            },
        )


# ---------------------------------------------------------------- acceso
@pytest.mark.parametrize(
    "metodo, ruta",
    [
        ("get", "/leads"),
        ("get", "/leads/indicadores"),
        ("get", "/ejecutivos"),
        ("get", "/auth/yo"),
        ("patch", "/leads/1"),
    ],
)
def test_rutas_privadas_exigen_sesion(cliente, metodo, ruta):
    extra = {"json": {"estado": "contactado"}} if metodo == "patch" else {}
    assert getattr(cliente, metodo)(ruta, **extra).status_code == 401
    falsa = {"Authorization": "Bearer token-falso"}
    assert getattr(cliente, metodo)(ruta, headers=falsa, **extra).status_code == 401


def test_login_con_datos_incorrectos_da_el_mismo_error(cliente):
    ejecutivo = _crear_ejecutivo()
    clave_mala = cliente.post(
        "/auth/login", json={"email": ejecutivo["email"], "password": "otra-clave"}
    )
    sin_cuenta = cliente.post("/auth/login", json={"email": f"nadie{SUFIJO}", "password": CLAVE})
    assert clave_mala.status_code == sin_cuenta.status_code == 401
    assert clave_mala.json() == sin_cuenta.json()  # no revela si el correo existe


def test_token_de_un_ejecutivo_desactivado_deja_de_servir(cliente, sesion):
    assert cliente.get("/auth/yo", headers=sesion["cabeceras"]).status_code == 200
    with conectar() as conn:
        conn.execute("UPDATE ejecutivo SET activo = false WHERE id = %s", (sesion["id"],))
    assert cliente.get("/auth/yo", headers=sesion["cabeceras"]).status_code == 401


# ---------------------------------------------------------------- formulario público
def test_formulario_publico_exige_consentimiento(cliente):
    base = {"nombre": "Cliente de prueba", "email": f"{uuid.uuid4().hex[:10]}{SUFIJO}"}
    assert cliente.post("/leads", json={**base, "consentimiento": False}).status_code == 422
    creado = cliente.post("/leads", json={**base, "consentimiento": True})
    assert creado.status_code == 201
    assert set(creado.json()) == {"id"}  # no devuelve datos personales


# ---------------------------------------------------------------- estados y asignación
def test_cambio_de_estado_guarda_fechas_y_historial(cliente, sesion):
    lead_id = _crear_lead(cliente)
    ruta, cabeceras = f"/leads/{lead_id}", sesion["cabeceras"]

    descartado = cliente.patch(ruta, json={"estado": "descartado"}, headers=cabeceras).json()
    assert descartado["estado"] == "descartado"
    assert (
        descartado["primera_respuesta_en"] is None
    )  # descartar sin contactar no cuenta como respuesta

    contactado = cliente.patch(ruta, json={"estado": "contactado"}, headers=cabeceras).json()
    primera = contactado["primera_respuesta_en"]
    assert primera is not None

    visita = cliente.patch(ruta, json={"estado": "visita_agendada"}, headers=cabeceras).json()
    assert visita["visita_agendada_en"] is not None
    assert visita["primera_respuesta_en"] == primera  # la primera respuesta no se pisa

    vuelta = cliente.patch(ruta, json={"estado": "nuevo"}, headers=cabeceras).json()
    assert vuelta["estado"] == "nuevo"
    assert vuelta["primera_respuesta_en"] == primera  # volver atrás no borra las fechas
    assert vuelta["visita_agendada_en"] == visita["visita_agendada_en"]

    with conectar() as conn:
        eventos = conn.execute(
            "SELECT count(*) AS total FROM lead_evento "
            "WHERE lead_id = %s AND tipo = 'estado' AND ejecutivo_id = %s",
            (lead_id, sesion["id"]),
        ).fetchone()["total"]
    assert eventos == 4


def test_asignacion_de_ejecutivo(cliente, sesion):
    lead_id = _crear_lead(cliente)
    ruta, cabeceras = f"/leads/{lead_id}", sesion["cabeceras"]

    asignado = cliente.patch(ruta, json={"ejecutivo_id": sesion["id"]}, headers=cabeceras).json()
    assert asignado["ejecutivo_id"] == sesion["id"]

    inactivo = _crear_ejecutivo(activo=False)
    rechazo = cliente.patch(ruta, json={"ejecutivo_id": inactivo["id"]}, headers=cabeceras)
    assert rechazo.status_code == 422

    liberado = cliente.patch(ruta, json={"ejecutivo_id": None}, headers=cabeceras).json()
    assert liberado["ejecutivo_id"] is None


def test_cambios_invalidos(cliente, sesion):
    lead_id = _crear_lead(cliente)
    cabeceras = sesion["cabeceras"]
    assert cliente.patch(f"/leads/{lead_id}", json={}, headers=cabeceras).status_code == 422
    assert (
        cliente.patch(
            f"/leads/{lead_id}", json={"estado": "inventado"}, headers=cabeceras
        ).status_code
        == 422
    )
    assert (
        cliente.patch(f"/leads/{lead_id}", json={"estado": None}, headers=cabeceras).status_code
        == 422
    )
    assert (
        cliente.patch(
            "/leads/999999999", json={"estado": "contactado"}, headers=cabeceras
        ).status_code
        == 404
    )


def test_listado_filtra_por_estado_y_asignacion(cliente, sesion):
    cabeceras = sesion["cabeceras"]
    asignado, libre = _crear_lead(cliente), _crear_lead(cliente)
    cliente.patch(
        f"/leads/{asignado}",
        json={"ejecutivo_id": sesion["id"], "estado": "contactado"},
        headers=cabeceras,
    )

    sin_asignar = cliente.get(
        "/leads", params={"sin_asignar": True, "limite": 100}, headers=cabeceras
    ).json()
    ids = {lead["id"] for lead in sin_asignar["resultados"]}
    assert libre in ids and asignado not in ids

    mios = cliente.get(
        "/leads", params={"ejecutivo_id": sesion["id"], "estado": "contactado"}, headers=cabeceras
    ).json()
    assert [lead["id"] for lead in mios["resultados"]] == [asignado]
    assert mios["total"] == 1
    assert mios["resultados"][0]["email"].endswith(SUFIJO)  # el ejecutivo sí ve los datos del lead


# ---------------------------------------------------------------- indicadores
def test_indicadores_con_datos_conocidos(cliente, sesion):
    # Marzo de 2001: un período lejano para no mezclarse con datos reales
    _lead_con_fechas("2001-03-05 10:00", "visita_agendada", minutos_respuesta=30, con_visita=True)
    _lead_con_fechas("2001-03-10 09:00", "contactado", minutos_respuesta=90)
    _lead_con_fechas("2001-03-15 12:00", "nuevo")
    _lead_con_fechas("2001-03-31 23:30", "descartado")  # último día del período, hora de Chile
    _lead_con_fechas("2001-04-01 00:30", "nuevo")  # ya es abril: no entra

    cabeceras = sesion["cabeceras"]
    respuesta = cliente.get(
        "/leads/indicadores",
        params={"desde": "2001-03-01", "hasta": "2001-03-31"},
        headers=cabeceras,
    ).json()

    periodo = respuesta["periodo"]
    assert periodo["dias"] == 31
    assert periodo["recibidas"] == 4
    assert periodo["con_respuesta"] == 2
    assert periodo["sin_respuesta"] == 1  # el descartado no cuenta como pendiente
    assert periodo["mediana_primera_respuesta_min"] == 60.0
    assert periodo["promedio_primera_respuesta_min"] == 60.0
    assert periodo["visitas_agendadas"] == 1
    assert periodo["tasa_visitas_pct"] == 25.0

    anterior = respuesta["anterior"]  # mismo largo (31 días), justo antes
    assert (anterior["desde"], anterior["hasta"]) == ("2001-01-29", "2001-02-28")
    assert anterior["recibidas"] == 0 and anterior["tasa_visitas_pct"] is None

    al_reves = cliente.get(
        "/leads/indicadores",
        params={"desde": "2001-03-31", "hasta": "2001-03-01"},
        headers=cabeceras,
    )
    assert al_reves.status_code == 422
