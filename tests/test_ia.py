"""Pruebas del módulo de IA que no necesitan base de datos ni claves de API."""

import json
from decimal import Decimal

import httpx
import pytest

from core.ia.catalogo import Atributo
from core.ia.evaluacion import Metrica, comparar, iguales, leer_etiquetas, total
from core.ia.prompt import AvisoParaIA, instrucciones, mensaje_lote, version_prompt
from core.ia.proveedores import (
    ClienteIA,
    ErrorProveedor,
    Gemini,
    Groq,
    LimiteExcedido,
    RespuestaModelo,
)
from core.ia.respuesta import convertir_valor, evidencia_en_texto, validar_lote

CATALOGO = [
    Atributo(1, "acepta_mascotas", "Acepta mascotas", "booleano", "true si acepta mascotas."),
    Atributo(2, "gastos_comunes_clp", "Gastos comunes", "numero", "Monto en pesos."),
    Atributo(3, "estacion_metro", "Estación de metro", "texto", "Nombre de la estación."),
]
AVISOS = [
    AvisoParaIA(10, "Depto en Ñuñoa", "Se aceptan mascotas. Gastos comunes $85.000. A pasos de "
                "metro Ñuble."),
    AvisoParaIA(11, "Depto Providencia", "No se aceptan mascotas. Edificio con conserjería."),
]


def respuesta(avisos: list[dict]) -> str:
    return json.dumps({"avisos": avisos}, ensure_ascii=False)


# --------------------------------------------------------------------------- prompt
def test_prompt_incluye_catalogo_y_reglas():
    texto = instrucciones(CATALOGO)
    for a in CATALOGO:
        assert a.codigo in texto and a.descripcion in texto
    assert "JSON" in texto and "evidencia" in texto


def test_version_cambia_si_cambia_el_catalogo():
    otra = CATALOGO[:2]
    assert version_prompt(CATALOGO) != version_prompt(otra)
    assert version_prompt(CATALOGO) == version_prompt(list(CATALOGO))


def test_mensaje_lote_en_json_y_recortado():
    largo = AvisoParaIA(1, "t", "x" * 10_000)
    datos = json.loads(mensaje_lote([largo]).split("\n", 1)[1])
    assert datos[0]["id"] == 1 and len(datos[0]["descripcion"]) == 3000


# --------------------------------------------------------------------------- validación
def test_lote_valido():
    texto = respuesta([
        {"id": 10, "atributos": {
            "acepta_mascotas": {"valor": True, "evidencia": "Se aceptan mascotas",
                                "confianza": 0.95},
            "gastos_comunes_clp": {"valor": 85000, "evidencia": "Gastos comunes $85.000"},
            "estacion_metro": {"valor": "Ñuble", "evidencia": "metro Ñuble"},
        }},
        {"id": 11, "atributos": {
            "acepta_mascotas": {"valor": False, "evidencia": "No se aceptan mascotas"},
        }},
    ])
    lote = validar_lote(texto, AVISOS, CATALOGO)
    assert lote.error is None and lote.faltantes == []
    a = {v.codigo: v for v in lote.avisos[10].valores}
    assert a["acepta_mascotas"].valor is True and a["acepta_mascotas"].confianza == 0.95
    assert a["gastos_comunes_clp"].valor == Decimal("85000")
    assert a["estacion_metro"].valor == "Ñuble"
    assert lote.avisos[11].valores[0].valor is False


def test_descarta_evidencia_inventada_y_codigos_o_tipos_malos():
    texto = respuesta([{"id": 11, "atributos": {
        "acepta_mascotas": {"valor": True, "evidencia": "pet friendly"},  # no está en el texto
        "piscina": {"valor": True, "evidencia": "Edificio con conserjería"},  # fuera del catálogo
        "gastos_comunes_clp": {"valor": "barato", "evidencia": "Edificio"},  # no es número
        "estacion_metro": {"valor": None},  # no lo menciona
    }}])
    res = validar_lote(texto, AVISOS, CATALOGO).avisos[11]
    assert res.valores == []
    assert len(res.descartados) == 3
    assert any("evidencia" in d for d in res.descartados)


def test_aviso_faltante_y_json_invalido():
    lote = validar_lote(respuesta([{"id": 10, "atributos": {}}]), AVISOS, CATALOGO)
    assert lote.faltantes == [11] and lote.avisos[10].valores == []
    roto = validar_lote("esto no es json", AVISOS, CATALOGO)
    assert roto.error and sorted(roto.faltantes) == [10, 11]


def test_acepta_json_entre_comillas_de_codigo():
    texto = "```json\n" + respuesta([{"id": 10, "atributos": {}}]) + "\n```"
    assert validar_lote(texto, AVISOS[:1], CATALOGO).avisos[10].valores == []


@pytest.mark.parametrize(
    "tipo, crudo, esperado",
    [
        ("booleano", "sí", True),
        ("booleano", "no", False),
        ("numero", "85.000", Decimal("85000")),
        ("numero", 1.5, Decimal("1.5")),
        ("texto", "  Los Leones ", "Los Leones"),
    ],
)
def test_convertir_valor(tipo, crudo, esperado):
    assert convertir_valor(tipo, crudo) == esperado


@pytest.mark.parametrize("tipo, crudo", [("booleano", 1), ("numero", True), ("numero", -5),
                                         ("texto", ""), ("texto", "x" * 100)])
def test_convertir_valor_invalido(tipo, crudo):
    with pytest.raises(ValueError):
        convertir_valor(tipo, crudo)


def test_evidencia_ignora_tildes_mayusculas_y_cortes():
    texto = "Hermoso depto. SE ACEPTAN MASCOTAS pequeñas. Metro Ñuble a 3 cuadras."
    assert evidencia_en_texto("se aceptan mascotas pequenas", texto)
    assert evidencia_en_texto("Hermoso depto... Metro Ñuble", texto)
    assert not evidencia_en_texto("piscina temperada", texto)
    assert not evidencia_en_texto("", texto)


# --------------------------------------------------------------------------- proveedores
def _cliente_http(respuestas: list[httpx.Response]) -> tuple[httpx.Client, list[httpx.Request]]:
    pedidos: list[httpx.Request] = []

    def manejar(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        return respuestas.pop(0)

    return httpx.Client(transport=httpx.MockTransport(manejar)), pedidos


def test_gemini_lee_texto_sin_pensamientos_y_tokens():
    http, pedidos = _cliente_http([httpx.Response(200, json={
        "candidates": [{"content": {"parts": [
            {"text": "pensando...", "thought": True}, {"text": '{"avisos": []}'}]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20,
                          "thoughtsTokenCount": 5},
    })])
    r = Gemini("clave", http=http).completar("sistema", "usuario")
    assert r.texto == '{"avisos": []}' and r.tokens_entrada == 100 and r.tokens_salida == 25
    assert pedidos[0].headers["x-goog-api-key"] == "clave"
    assert "gemini-3.1-flash-lite:generateContent" in str(pedidos[0].url)


def test_groq_lee_respuesta_y_costo():
    http, pedidos = _cliente_http([httpx.Response(200, json={
        "choices": [{"message": {"content": '{"avisos": []}'}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
    })])
    r = Groq("clave", http=http).completar("s", "u")
    assert r.texto == '{"avisos": []}' and r.costo_usd() == Decimal("0.75")
    cuerpo = json.loads(pedidos[0].content)
    assert cuerpo["response_format"] == {"type": "json_object"}
    assert pedidos[0].headers["authorization"] == "Bearer clave"


def test_429_lee_espera_del_cuerpo_de_gemini():
    http, _ = _cliente_http([httpx.Response(429, text='{"details": [{"retryDelay": "17s"}]}')])
    with pytest.raises(LimiteExcedido) as e:
        Gemini("clave", http=http).completar("s", "u")
    assert e.value.espera == 17


class Falso:
    """Proveedor de prueba: devuelve o lanza lo que se le indique, en orden."""

    def __init__(self, nombre, salidas):
        self.nombre, self.modelo, self.salidas, self.llamadas = nombre, "falso", salidas, 0

    def completar(self, sistema, usuario):
        self.llamadas += 1
        salida = self.salidas.pop(0)
        if isinstance(salida, Exception):
            raise salida
        return RespuestaModelo(salida, self.nombre, self.modelo, 10, 5)


def test_cliente_pasa_al_siguiente_si_hay_limite():
    a = Falso("a", [LimiteExcedido("a: límite", 30)])
    b = Falso("b", ["ok"])
    assert ClienteIA([a, b], dormir=lambda s: None).completar("s", "u").proveedor == "b"


def test_cliente_espera_si_todos_estan_limitados():
    esperas = []
    a = Falso("a", [LimiteExcedido("límite", 12), "ok"])
    b = Falso("b", [LimiteExcedido("límite", 40)])
    r = ClienteIA([a, b], dormir=esperas.append).completar("s", "u")
    assert r.proveedor == "a" and esperas == [12]


def test_cliente_no_reintenta_errores_de_configuracion():
    a = Falso("a", [ErrorProveedor("a respondió 400: modelo no existe")])
    with pytest.raises(ErrorProveedor):
        ClienteIA([a], dormir=lambda s: pytest.fail("no debía esperar")).completar("s", "u")
    assert a.llamadas == 1


# --------------------------------------------------------------------------- evaluación
def test_leer_etiquetas_y_comparar(tmp_path):
    csv = tmp_path / "v.csv"
    csv.write_text(
        "publicacion_id;titulo;acepta_mascotas;gastos_comunes_clp;estacion_metro;"
        "etiquetado_por\n"
        "10;a;si;85.000;Ñuble;Samuel\n"
        "11;b;no;;;Martín\n"
        "12;c;quizás;;;Martín\n",
        encoding="utf-8-sig",
    )
    et = leer_etiquetas(csv, CATALOGO)
    assert et.ids == [10, 11, 12] and et.autores[11] == "Martín"
    assert et.valores[(10, "gastos_comunes_clp")] == Decimal("85000")
    assert len(et.errores) == 1  # "quizás" no es si/no

    tipos = {a.codigo: a.tipo_dato for a in CATALOGO}
    ia = {
        (10, "acepta_mascotas"): True,                   # acierto
        (10, "gastos_comunes_clp"): Decimal("86000"),     # distinto (> 1%)
        (11, "acepta_mascotas"): False,                  # acierto
        (11, "estacion_metro"): "Los Leones",            # inventado
    }
    m = comparar(et.valores, ia, [10, 11], tipos)
    assert m["acepta_mascotas"].aciertos == 2 and m["acepta_mascotas"].precision == 1
    assert m["gastos_comunes_clp"].valor_distinto == 1
    assert m["estacion_metro"].inventados == 1 and m["estacion_metro"].omitidos == 1
    t = total(m)
    assert (t.aciertos, t.predichos) == (2, 4) and t.precision == 0.5


def test_iguales_con_tolerancia():
    assert iguales("numero", Decimal("85000"), Decimal("85500"))
    assert iguales("texto", "Los Leones", "los leones")
    assert iguales("texto", "Ñuble", "Estación Ñuble")
    assert not iguales("booleano", True, False)
    assert Metrica().precision is None
