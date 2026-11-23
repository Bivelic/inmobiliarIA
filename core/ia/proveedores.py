"""Llamadas a los modelos de IA (Gemini y Groq) detrás de una sola interfaz.

El resto del código solo usa `ClienteIA.completar(sistema, usuario)`. Para cambiar de
proveedor basta con cambiar IA_PROVEEDORES en el .env (riesgo R-11 del registro).

Si un proveedor responde "límite excedido" (429) o falla, se prueba el siguiente; si todos
están limitados, se espera lo que piden y se reintenta.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import httpx

from core.config import ia_clave, ia_modelo, ia_proveedores

log = logging.getLogger(__name__)

# USD por millón de tokens (entrada, salida) en el plan PAGADO, solo como referencia para
# el control de costos (4.3.3). En el plan gratuito el gasto real es 0.
PRECIOS_USD_POR_MILLON = {
    "gemini-3.1-flash-lite": (Decimal("0.25"), Decimal("1.50")),
    "openai/gpt-oss-120b": (Decimal("0.15"), Decimal("0.60")),
}


@dataclass
class RespuestaModelo:
    texto: str
    proveedor: str
    modelo: str
    tokens_entrada: int | None = None
    tokens_salida: int | None = None

    @property
    def nombre_modelo(self) -> str:
        return f"{self.proveedor}:{self.modelo}"

    def costo_usd(self) -> Decimal | None:
        precios = PRECIOS_USD_POR_MILLON.get(self.modelo)
        if precios is None or self.tokens_entrada is None or self.tokens_salida is None:
            return None
        entrada, salida = precios
        return (self.tokens_entrada * entrada + self.tokens_salida * salida) / Decimal(1_000_000)


class LimiteExcedido(Exception):
    """El proveedor respondió 429 (cuota o límite por minuto)."""

    def __init__(self, mensaje: str, espera: float | None = None):
        super().__init__(mensaje)
        self.espera = espera


class ErrorProveedor(Exception):
    def __init__(self, mensaje: str, reintentable: bool = False):
        super().__init__(mensaje)
        self.reintentable = reintentable


def _segundos(texto: str | None) -> float | None:
    """'30', '30s' o '1.5s' -> segundos."""
    if not texto:
        return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*$", str(texto))
    return float(m.group(1)) if m else None


class Proveedor:
    nombre = "base"
    modelo_por_defecto = ""

    def __init__(self, clave: str, modelo: str | None = None, http: httpx.Client | None = None):
        self.clave = clave
        self.modelo = modelo or self.modelo_por_defecto
        self.http = http or httpx.Client(timeout=90)
        self.timeout_siguiente: float | None = None  # lo fija ClienteIA si hay tiempo total

    def completar(self, sistema: str, usuario: str) -> RespuestaModelo:
        raise NotImplementedError

    def _post(self, url: str, headers: dict, cuerpo: dict) -> dict:
        try:
            r = self.http.post(
                url, headers=headers, json=cuerpo,
                timeout=self.timeout_siguiente or httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.TimeoutException as e:
            raise ErrorProveedor(f"{self.nombre}: sin respuesta a tiempo", reintentable=True) from e
        except httpx.TransportError as e:
            raise ErrorProveedor(
                f"{self.nombre}: error de conexión ({e})", reintentable=True
            ) from e
        if r.status_code == 429:
            raise LimiteExcedido(f"{self.nombre}: límite excedido", self._espera_429(r))
        if r.status_code >= 400:
            raise ErrorProveedor(
                f"{self.nombre} respondió {r.status_code}: {r.text[:300]}",
                reintentable=r.status_code >= 500,
            )
        return r.json()

    @staticmethod
    def _espera_429(r: httpx.Response) -> float | None:
        espera = _segundos(r.headers.get("retry-after"))
        if espera is None:  # Gemini lo informa en el cuerpo: "retryDelay": "30s"
            m = re.search(r'"retryDelay"\s*:\s*"([\d.]+s)"', r.text)
            espera = _segundos(m.group(1)) if m else None
        return espera


class Gemini(Proveedor):
    nombre = "gemini"
    modelo_por_defecto = "gemini-3.1-flash-lite"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

    def completar(self, sistema: str, usuario: str) -> RespuestaModelo:
        datos = self._post(
            self.URL.format(modelo=self.modelo),
            {"x-goog-api-key": self.clave},
            {
                "systemInstruction": {"parts": [{"text": sistema}]},
                "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        candidatos = datos.get("candidates") or []
        if not candidatos:
            motivo = (datos.get("promptFeedback") or {}).get("blockReason", "sin candidatos")
            raise ErrorProveedor(f"gemini no devolvió respuesta ({motivo})")
        partes = (candidatos[0].get("content") or {}).get("parts") or []
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        uso = datos.get("usageMetadata") or {}
        return RespuestaModelo(
            texto=texto,
            proveedor=self.nombre,
            modelo=self.modelo,
            tokens_entrada=uso.get("promptTokenCount"),
            tokens_salida=(uso.get("candidatesTokenCount") or 0)
            + (uso.get("thoughtsTokenCount") or 0),
        )


class Groq(Proveedor):
    nombre = "groq"
    modelo_por_defecto = "openai/gpt-oss-120b"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def completar(self, sistema: str, usuario: str) -> RespuestaModelo:
        datos = self._post(
            self.URL,
            {"Authorization": f"Bearer {self.clave}"},
            {
                "model": self.modelo,
                "messages": [
                    {"role": "system", "content": sistema},
                    {"role": "user", "content": usuario},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        try:
            texto = datos["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ErrorProveedor("groq devolvió una respuesta sin contenido") from e
        uso = datos.get("usage") or {}
        return RespuestaModelo(
            texto=texto,
            proveedor=self.nombre,
            modelo=self.modelo,
            tokens_entrada=uso.get("prompt_tokens"),
            tokens_salida=uso.get("completion_tokens"),
        )


CLASES: dict[str, type[Proveedor]] = {"gemini": Gemini, "groq": Groq}


def crear_proveedores(
    nombres: list[str] | None = None, http: httpx.Client | None = None
) -> list[Proveedor]:
    """Proveedores configurados en el .env, en orden. Omite los que no tienen clave."""
    proveedores = []
    for nombre in nombres or ia_proveedores():
        clase = CLASES.get(nombre)
        if clase is None:
            raise RuntimeError(f"Proveedor de IA desconocido: {nombre} (opciones: {list(CLASES)})")
        clave = ia_clave(nombre)
        if not clave:
            log.warning("Sin %s_API_KEY en el .env: se omite %s", nombre.upper(), nombre)
            continue
        proveedores.append(clase(clave, ia_modelo(nombre, clase.modelo_por_defecto), http))
    if not proveedores:
        raise RuntimeError(
            "No hay ningún proveedor de IA con clave. Agrega GEMINI_API_KEY y/o GROQ_API_KEY "
            "al .env (ver docs/IA_EXTRACCION.md)."
        )
    return proveedores


class ClienteIA:
    """Prueba los proveedores en orden; si todos están limitados, espera y reintenta."""

    def __init__(
        self,
        proveedores: list[Proveedor],
        rondas: int = 4,
        espera_maxima: float = 90,
        dormir: Callable[[float], None] = time.sleep,
        tiempo_total: float | None = None,
    ):
        if not proveedores:
            raise ValueError("ClienteIA necesita al menos un proveedor")
        self.proveedores = proveedores
        self.rondas = rondas
        self.espera_maxima = espera_maxima
        self.dormir = dormir
        self.tiempo_total = tiempo_total  # segundos para TODA la llamada (ej. búsquedas en vivo)

    def completar(self, sistema: str, usuario: str) -> RespuestaModelo:
        ultimo: Exception | None = None
        inicio = time.monotonic()
        for ronda in range(1, self.rondas + 1):
            esperas: list[float] = []
            for p in self.proveedores:
                if self.tiempo_total is not None:
                    restante = self.tiempo_total - (time.monotonic() - inicio)
                    if restante < 0.3:
                        raise ErrorProveedor(f"sin tiempo para responder ({ultimo})")
                    p.timeout_siguiente = restante
                try:
                    return p.completar(sistema, usuario)
                except LimiteExcedido as e:
                    log.warning("%s (ronda %d)", e, ronda)
                    esperas.append(e.espera if e.espera is not None else 20.0)
                    ultimo = e
                except ErrorProveedor as e:
                    log.warning("%s (ronda %d)", e, ronda)
                    if e.reintentable:
                        esperas.append(5.0)
                    ultimo = e
            if not esperas or ronda == self.rondas:
                break  # errores que no se arreglan esperando (clave o modelo mal puestos)
            espera = min(min(esperas), self.espera_maxima)
            log.info("Todos los proveedores ocupados; esperando %.0f s", espera)
            self.dormir(espera)
        raise ErrorProveedor(f"Ningún proveedor respondió: {ultimo}")
