"""Pruebas de la API. Necesitan una base con el esquema cargado (DATABASE_URL en .env);
si no hay base disponible, se saltan."""

import pytest
from fastapi.testclient import TestClient

try:
    from core.db import conectar

    with conectar() as _c:
        _c.execute("SELECT 1 FROM publicacion LIMIT 1")
    HAY_BASE = True
except Exception:  # noqa: BLE001
    HAY_BASE = False

pytestmark = pytest.mark.skipif(not HAY_BASE, reason="sin base de datos disponible")


@pytest.fixture(scope="module")
def cliente():
    from api.main import app

    return TestClient(app)


def test_health(cliente):
    assert cliente.get("/health").json() == {"estado": "ok"}


def test_listado_responde_con_formato(cliente):
    r = cliente.get("/publicaciones", params={"limite": 5})
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"total", "resultados"}
    for aviso in cuerpo["resultados"]:
        assert aviso["url"].startswith("http")
        assert "descripcion" not in aviso  # solo extracto, nunca el texto completo


def test_filtros_invalidos(cliente):
    assert cliente.get("/publicaciones", params={"limite": 500}).status_code == 422


def test_detalle_inexistente(cliente):
    assert cliente.get("/publicaciones/999999999").status_code == 404


def test_metricas(cliente):
    r = cliente.get("/metricas")
    assert r.status_code == 200
    assert {m["portal"] for m in r.json()} >= {"chilepropiedades", "yapo", "economicos"}


@pytest.mark.parametrize("orden", ["recientes", "precio_asc", "precio_desc"])
def test_ordenes_validos(cliente, orden):
    assert cliente.get("/publicaciones", params={"orden": orden}).status_code == 200


def test_orden_invalido(cliente):
    assert cliente.get("/publicaciones", params={"orden": "x; DROP TABLE"}).status_code == 422
