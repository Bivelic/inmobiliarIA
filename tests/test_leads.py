"""Solicitudes de contacto (RF-07): validación, registro, correo a Aurora y métricas."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from core.leads import SolicitudContacto, correo_html, notificar

VALIDA = {
    "publicacion_id": 1, "nombre": "Ana Pérez", "email": " Ana@Correo.CL ",
    "telefono": "+56 9 1234 5678", "mensaje": "Me interesa", "consentimiento": True,
}


# --------------------------------------------------------------------------- sin base
def test_solicitud_valida_se_normaliza():
    s = SolicitudContacto(**VALIDA)
    assert s.email == "ana@correo.cl" and s.nombre == "Ana Pérez"


@pytest.mark.parametrize("cambio", [
    {"consentimiento": False},
    {"email": "no-es-correo"},
    {"nombre": " "},
    {"telefono": "abc"},
    {"mensaje": "x" * 1001},
])
def test_solicitud_invalida(cambio):
    with pytest.raises(ValidationError):
        SolicitudContacto(**{**VALIDA, **cambio})


def _lead(**cambios):
    s = SolicitudContacto(**{**VALIDA, **cambios})
    return {
        "id": 7, "creado_en": datetime(2026, 11, 20, 15, 30, tzinfo=UTC), "solicitud": s,
        "busqueda": "depto en Ñuñoa que acepte perros",
        "aviso": {"titulo": "Depto 2D Ñuñoa", "url": "https://ejemplo.cl/1", "portal": "Yapo",
                  "precio_clp": Decimal("550000"), "comuna": "Ñuñoa"},
    }


def test_correo_escapa_lo_que_escribe_el_usuario():
    asunto, cuerpo = correo_html(_lead(mensaje="<script>alert(1)</script>"))
    assert "Nuevo lead #7" in asunto and "Ana Pérez" in asunto
    assert "<script>" not in cuerpo and "&lt;script&gt;" in cuerpo
    assert "$550.000" in cuerpo and "depto en Ñuñoa que acepte perros" in cuerpo


def test_notificar_envia_a_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_prueba")
    monkeypatch.setenv("LEADS_CORREO_DESTINO", "aurorapropiedades0@gmail.com")
    pedidos = []

    def manejar(request):
        pedidos.append(request)
        return httpx.Response(200, json={"id": "abc"})

    http = httpx.Client(transport=httpx.MockTransport(manejar))
    assert notificar(_lead(), http) is True
    cuerpo = json.loads(pedidos[0].content)
    assert pedidos[0].headers["authorization"] == "Bearer re_prueba"
    assert cuerpo["to"] == ["aurorapropiedades0@gmail.com"]
    assert cuerpo["reply_to"] == "ana@correo.cl"
    assert cuerpo["from"] == "InmobiliarIA <onboarding@resend.dev>"


def test_notificar_no_se_cae_si_resend_falla_o_falta_configurar(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert notificar(_lead()) is False
    monkeypatch.setenv("RESEND_API_KEY", "re_prueba")
    monkeypatch.setenv("LEADS_CORREO_DESTINO", "x@y.cl")
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="no")))
    assert notificar(_lead(), http) is False


# --------------------------------------------------------------------------- con base
try:
    from core.db import conectar

    with conectar() as _c:
        _c.execute("SELECT 1 FROM lead LIMIT 1")
    HAY_BASE = True
except Exception:  # noqa: BLE001
    HAY_BASE = False

con_base = pytest.mark.skipif(not HAY_BASE, reason="sin base de datos disponible")


@pytest.fixture
def aviso():
    with conectar(autocommit=True) as c:
        c.execute("DELETE FROM publicacion WHERE id_externo = 'test-lead-1'")
        portal = c.execute("SELECT id FROM portal WHERE codigo = 'yapo'").fetchone()["id"]
        pid = c.execute(
            """
            INSERT INTO publicacion (portal_id, id_externo, url, operacion, tipo_propiedad,
                titulo, precio_monto, precio_moneda, precio_clp, hash_contenido)
            VALUES (%s, 'test-lead-1', 'https://ejemplo.cl/lead', 'arriendo', 'departamento',
                    'Depto para lead', 500000, 'CLP', 500000, 'x')
            RETURNING id
            """,
            (portal,),
        ).fetchone()["id"]
        yield c, pid
        c.execute("DELETE FROM lead WHERE email = 'ana@correo.cl'")
        c.execute("DELETE FROM publicacion WHERE id = %s", (pid,))


@con_base
def test_post_leads_guarda_y_avisa(aviso, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as api

    c, pid = aviso
    enviados = []
    monkeypatch.setattr(api, "notificar", lambda lead: enviados.append(lead["id"]))
    r = TestClient(api.app).post("/leads", json={**VALIDA, "publicacion_id": pid})
    assert r.status_code == 201
    lead_id = r.json()["id"]
    assert "email" not in r.json()  # la respuesta no devuelve datos personales
    fila = c.execute("SELECT * FROM lead WHERE id = %s", (lead_id,)).fetchone()
    assert fila["email"] == "ana@correo.cl" and fila["consentimiento"] and fila["estado"] == "nuevo"
    assert fila["publicacion_id"] == pid
    assert enviados == [lead_id]


@con_base
def test_post_leads_rechaza_sin_consentimiento_o_aviso_inexistente(aviso, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as api

    _, pid = aviso
    monkeypatch.setattr(api, "notificar", lambda lead: None)
    cliente = TestClient(api.app)
    sin = cliente.post("/leads", json={**VALIDA, "publicacion_id": pid, "consentimiento": False})
    assert sin.status_code == 422
    assert cliente.post("/leads", json={**VALIDA, "publicacion_id": 999_999_999}).status_code == 404


@con_base
def test_metricas_leads(aviso, monkeypatch):
    from fastapi.testclient import TestClient

    import api.main as api

    _, pid = aviso
    monkeypatch.setattr(api, "notificar", lambda lead: None)
    cliente = TestClient(api.app)
    antes = cliente.get("/metricas/leads").json()["leads"]
    cliente.post("/leads", json={**VALIDA, "publicacion_id": pid})
    datos = cliente.get("/metricas/leads").json()
    assert datos["leads"] == antes + 1 and "tasa_contacto" in datos
