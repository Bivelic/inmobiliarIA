"""Validación de lo que responde el modelo (EDT 4.3.2 y RF-03.06).

Un atributo se guarda solo si:
  - su código está en el catálogo,
  - su valor tiene el tipo correcto (booleano, número o texto),
  - su "evidencia" aparece de verdad en el título o la descripción del aviso.
Lo demás se descarta y se cuenta, para no inventar datos que el aviso no dice.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

from core.ia.catalogo import Atributo
from core.ia.prompt import AvisoParaIA
from core.normalizacion import numero

MAX_TEXTO = 80
_VERDADERO = {"true", "si", "sí", "yes"}
_FALSO = {"false", "no"}


@dataclass
class ValorExtraido:
    atributo_id: int
    codigo: str
    tipo: str
    valor: bool | Decimal | str
    evidencia: str
    confianza: float | None


@dataclass
class ResultadoAviso:
    publicacion_id: int
    valores: list[ValorExtraido] = field(default_factory=list)
    descartados: list[str] = field(default_factory=list)  # motivo de cada atributo descartado


@dataclass
class ResultadoLote:
    avisos: dict[int, ResultadoAviso] = field(default_factory=dict)
    faltantes: list[int] = field(default_factory=list)  # avisos que el modelo no devolvió
    error: str | None = None  # la respuesta completa no se pudo leer


class RespuestaInvalida(ValueError):
    pass


# --------------------------------------------------------------------------- utilidades
def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples (para comparar textos)."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def evidencia_en_texto(evidencia: str, texto: str) -> bool:
    """La evidencia (o cada trozo, si el modelo la cortó con '...') aparece en el texto."""
    base = normalizar(texto)
    trozos = [normalizar(t).strip(" \"'“”.,;:") for t in re.split(r"\.\.\.|…", evidencia)]
    trozos = [t for t in trozos if len(t) >= 3]
    return bool(trozos) and all(t in base for t in trozos)


def leer_json(texto: str) -> object:
    """Lee el JSON aunque venga envuelto en ```json ... ```."""
    limpio = texto.strip()
    if limpio.startswith("```"):
        limpio = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", limpio)
    try:
        return json.loads(limpio)
    except json.JSONDecodeError as e:
        raise RespuestaInvalida(f"la respuesta no es JSON válido: {e}") from e


def convertir_valor(tipo: str, crudo: object) -> bool | Decimal | str:
    """Convierte el valor al tipo del catálogo o lanza ValueError."""
    if tipo == "booleano":
        if isinstance(crudo, bool):
            return crudo
        if isinstance(crudo, str) and normalizar(crudo) in _VERDADERO | _FALSO:
            return normalizar(crudo) in _VERDADERO
        raise ValueError(f"se esperaba true/false y llegó {crudo!r}")
    if tipo == "numero":
        if isinstance(crudo, bool):
            raise ValueError("se esperaba un número y llegó true/false")
        if isinstance(crudo, int | float):
            valor = Decimal(str(crudo))
        elif isinstance(crudo, str):
            valor = numero(crudo)
        else:
            valor = None
        if valor is None or valor < 0 or valor >= Decimal("1e10"):
            raise ValueError(f"número inválido: {crudo!r}")
        return valor
    if tipo == "texto":
        if not isinstance(crudo, str) or not crudo.strip():
            raise ValueError(f"se esperaba texto y llegó {crudo!r}")
        valor = crudo.strip()
        if len(valor) > MAX_TEXTO:
            raise ValueError("texto demasiado largo")
        return valor
    raise ValueError(f"tipo de dato desconocido: {tipo}")


def _confianza(crudo: object) -> float | None:
    if isinstance(crudo, bool) or not isinstance(crudo, int | float):
        return None
    return round(min(max(float(crudo), 0.0), 1.0), 2)


def _items_atributos(crudo: object) -> list[tuple[str, object]]:
    """Acepta {"codigo": {...}} o [{"codigo": "...", ...}]."""
    if isinstance(crudo, dict):
        return list(crudo.items())
    if isinstance(crudo, list):
        return [(str(x.get("codigo")), x) for x in crudo if isinstance(x, dict)]
    return []


# --------------------------------------------------------------------------- validación
def validar_aviso(
    aviso: AvisoParaIA, atributos_crudos: object, catalogo: dict[str, Atributo]
) -> ResultadoAviso:
    resultado = ResultadoAviso(publicacion_id=aviso.id)
    texto = f"{aviso.titulo}\n{aviso.descripcion or ''}"
    for codigo, dato in _items_atributos(atributos_crudos):
        if not isinstance(dato, dict):
            dato = {"valor": dato}
        if dato.get("valor") is None:
            continue  # el modelo dice "no se menciona": no es un descarte
        atributo = catalogo.get(codigo)
        if atributo is None:
            resultado.descartados.append(f"{codigo}: no está en el catálogo")
            continue
        try:
            valor = convertir_valor(atributo.tipo_dato, dato.get("valor"))
        except ValueError as e:
            resultado.descartados.append(f"{codigo}: {e}")
            continue
        evidencia = str(dato.get("evidencia") or "").strip()
        if not evidencia_en_texto(evidencia, texto):
            resultado.descartados.append(f"{codigo}: evidencia que no está en el aviso")
            continue
        resultado.valores.append(
            ValorExtraido(
                atributo_id=atributo.id,
                codigo=codigo,
                tipo=atributo.tipo_dato,
                valor=valor,
                evidencia=evidencia[:200],
                confianza=_confianza(dato.get("confianza")),
            )
        )
    return resultado


def validar_lote(
    texto_respuesta: str, avisos: list[AvisoParaIA], catalogo: list[Atributo]
) -> ResultadoLote:
    """Valida la respuesta completa de un lote. Nunca lanza excepción: los problemas
    quedan en `error` (respuesta ilegible) o en `faltantes` (avisos no devueltos)."""
    por_codigo = {a.codigo: a for a in catalogo}
    por_id = {a.id: a for a in avisos}
    lote = ResultadoLote()
    try:
        datos = leer_json(texto_respuesta)
    except RespuestaInvalida as e:
        lote.error = str(e)
        lote.faltantes = list(por_id)
        return lote

    items = datos.get("avisos") if isinstance(datos, dict) else datos
    if not isinstance(items, list):
        lote.error = 'la respuesta no trae la lista "avisos"'
        lote.faltantes = list(por_id)
        return lote

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if pid in por_id and pid not in lote.avisos:
            lote.avisos[pid] = validar_aviso(por_id[pid], item.get("atributos"), por_codigo)
    lote.faltantes = [pid for pid in por_id if pid not in lote.avisos]
    return lote
