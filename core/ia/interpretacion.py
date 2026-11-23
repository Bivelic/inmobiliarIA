"""Interpretación de búsquedas escritas (EDT 4.4.1, RF-04.03).

Convierte "depto en Ñuñoa que acepte perros bajo 600 mil" en criterios:
    {"operacion": "arriendo", "comunas": ["nunoa"], "precio_max": 600000, "moneda": "CLP",
     "atributos": {"acepta_mascotas": true}}

Los filtros (operación, tipo, comunas, precio, dormitorios, baños, m²) se aplican tal cual;
los atributos son preferencias que suben el puntaje (core/buscador.py).
Cada interpretación se guarda con la búsqueda; si el mismo texto se repite, se reutiliza
sin volver a llamar a la IA (rapidez y costo).
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg

from core.ia.catalogo import Atributo
from core.ia.proveedores import ClienteIA, ErrorProveedor, LimiteExcedido
from core.ia.respuesta import RespuestaInvalida, convertir_valor, leer_json, normalizar
from core.normalizacion import numero, slug

log = logging.getLogger(__name__)

VERSION_REGLAS = "b1"
MAX_TEXTO = 300

REGLAS = """\
Interpretas búsquedas de propiedades en Chile (Región Metropolitana) escritas por personas.
Devuelve SOLO lo que la persona pide de forma explícita; lo que no menciona va en null o se omite.

Responde únicamente con un objeto JSON con esta forma:
{"operacion": "arriendo" | "venta" | null,
 "tipo_propiedad": "departamento" | "casa" | "estudio" | null,
 "comunas": ["Ñuñoa", ...],
 "precio_min": número | null, "precio_max": número | null, "moneda": "CLP" | "UF",
 "dormitorios_min": entero | null, "banos_min": entero | null, "m2_min": número | null,
 "atributos": {"<codigo>": valor}}

Reglas:
1. Montos como número: "600 mil" = 600000; "1,2 millones" = 1200000; "20 UF" = 20 con moneda "UF".
   "hasta", "máximo", "menos de" o "bajo" van en precio_max; "desde" o "más de" en precio_min.
2. "depto" o "departamento" = departamento. "arriendo", "arrendar" o "alquiler" = arriendo;
   "comprar" o "venta" = venta.
3. "2 dormitorios", "2D" o "2 piezas" = dormitorios_min 2. "2 baños" o "2B" = banos_min 2.
4. comunas: nombres de comunas de la Región Metropolitana. Si nombra un barrio o una estación
   que pertenece claramente a una comuna (ej. "Barrio Italia"), usa esa comuna.
5. atributos: solo códigos del catálogo, con el tipo indicado. Ejemplos: "acepte perros",
   "mascotas" o "gato" = acepta_mascotas true; "cerca del metro" = cerca_metro true;
   "cerca del metro Los Leones" = estacion_metro "Los Leones"; "gastos comunes de menos de
   80 mil" = gastos_comunes_clp 80000 (se entiende como máximo); "con estacionamiento" =
   estacionamiento true; "amoblado" = amoblado true.
"""


@dataclass
class Criterios:
    operacion: str | None = None
    tipo_propiedad: str | None = None
    comunas: list[str] = field(default_factory=list)  # slugs de la tabla comuna
    precio_min: Decimal | None = None
    precio_max: Decimal | None = None
    moneda: str = "CLP"
    dormitorios_min: int | None = None
    banos_min: int | None = None
    m2_min: Decimal | None = None
    atributos: dict[str, bool | Decimal | str] = field(default_factory=dict)

    def a_json(self) -> dict:
        def simple(v):
            return float(v) if isinstance(v, Decimal) else v

        return {
            "operacion": self.operacion,
            "tipo_propiedad": self.tipo_propiedad,
            "comunas": self.comunas,
            "precio_min": simple(self.precio_min),
            "precio_max": simple(self.precio_max),
            "moneda": self.moneda,
            "dormitorios_min": self.dormitorios_min,
            "banos_min": self.banos_min,
            "m2_min": simple(self.m2_min),
            "atributos": {k: simple(v) for k, v in self.atributos.items()},
        }

    @classmethod
    def desde_json(cls, d: dict) -> "Criterios":
        def dec(v):
            return Decimal(str(v)) if v is not None else None

        return cls(
            operacion=d.get("operacion"),
            tipo_propiedad=d.get("tipo_propiedad"),
            comunas=list(d.get("comunas") or []),
            precio_min=dec(d.get("precio_min")),
            precio_max=dec(d.get("precio_max")),
            moneda=d.get("moneda") or "CLP",
            dormitorios_min=d.get("dormitorios_min"),
            banos_min=d.get("banos_min"),
            m2_min=dec(d.get("m2_min")),
            atributos={
                k: (dec(v) if isinstance(v, int | float) and not isinstance(v, bool) else v)
                for k, v in (d.get("atributos") or {}).items()
            },
        )


@dataclass
class Interpretacion:
    criterios: Criterios
    interpretado: bool  # False = la IA no respondió y se usa búsqueda por palabras
    desde_cache: bool = False
    ignorado: list[str] = field(default_factory=list)  # lo que la IA devolvió y no se usó
    aviso: str | None = None


# --------------------------------------------------------------------------- prompt
def instrucciones(catalogo: list[Atributo]) -> str:
    lineas = "\n".join(f"- {a.codigo} ({a.tipo_dato}): {a.nombre}" for a in catalogo)
    return f"{REGLAS}\nCatálogo de atributos:\n{lineas}\n"


def version(catalogo: list[Atributo]) -> str:
    huella = hashlib.sha256(instrucciones(catalogo).encode("utf-8")).hexdigest()[:8]
    return f"{VERSION_REGLAS}-{huella}"


def texto_normalizado(texto: str) -> str:
    return normalizar(texto)[:MAX_TEXTO]


# --------------------------------------------------------------------------- validación
def _entero(v) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 20 else None


def _monto(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    valor = Decimal(str(v)) if isinstance(v, int | float) else numero(str(v))
    return valor if valor is not None and valor > 0 else None


def validar_criterios(
    datos: object, catalogo: list[Atributo], comunas: dict[str, str]
) -> tuple[Criterios, list[str]]:
    """`comunas` = {nombre normalizado o slug: slug}. Devuelve los criterios y lo ignorado."""
    if not isinstance(datos, dict):
        raise RespuestaInvalida("la interpretación no es un objeto JSON")
    ignorado: list[str] = []
    c = Criterios()
    if datos.get("operacion") in ("arriendo", "venta"):
        c.operacion = datos["operacion"]
    if datos.get("tipo_propiedad") in ("departamento", "casa", "estudio"):
        c.tipo_propiedad = datos["tipo_propiedad"]
    for nombre in datos.get("comunas") or []:
        s = comunas.get(normalizar(str(nombre))) or comunas.get(slug(str(nombre)))
        if s and s not in c.comunas:
            c.comunas.append(s)
        elif not s:
            ignorado.append(f"comuna desconocida: {nombre}")
    c.moneda = "UF" if str(datos.get("moneda") or "").upper() == "UF" else "CLP"
    c.precio_min, c.precio_max = _monto(datos.get("precio_min")), _monto(datos.get("precio_max"))
    if c.precio_min and c.precio_max and c.precio_min > c.precio_max:
        c.precio_min, c.precio_max = c.precio_max, c.precio_min
    c.dormitorios_min = _entero(datos.get("dormitorios_min"))
    c.banos_min = _entero(datos.get("banos_min"))
    c.m2_min = _monto(datos.get("m2_min"))

    tipos = {a.codigo: a.tipo_dato for a in catalogo}
    atributos = datos.get("atributos") or {}
    if isinstance(atributos, dict):
        for codigo, valor in atributos.items():
            if isinstance(valor, dict):
                valor = valor.get("valor")
            if valor is None:
                continue
            if codigo not in tipos:
                ignorado.append(f"atributo desconocido: {codigo}")
                continue
            try:
                c.atributos[codigo] = convertir_valor(tipos[codigo], valor)
            except ValueError as e:
                ignorado.append(f"{codigo}: {e}")
    return c, ignorado


# --------------------------------------------------------------------------- base de datos
def mapa_comunas(conn: psycopg.Connection) -> dict[str, str]:
    mapa = {}
    for f in conn.execute("SELECT nombre, slug FROM comuna").fetchall():
        mapa[normalizar(f["nombre"])] = f["slug"]
        mapa[f["slug"]] = f["slug"]
    return mapa


def desde_cache(conn: psycopg.Connection, texto: str, ver: str) -> Criterios | None:
    fila = conn.execute(
        """
        SELECT criterios->'_ia' AS ia FROM busqueda
        WHERE criterios->>'_version' = %s AND criterios->>'_texto' = %s
          AND criterios ? '_ia'
        ORDER BY id DESC LIMIT 1
        """,
        (ver, texto_normalizado(texto)),
    ).fetchone()
    return Criterios.desde_json(fila["ia"]) if fila else None


def criterios_para_guardar(
    finales: Criterios, i: Interpretacion | None, texto: str, ver: str
) -> dict:
    """JSON que se guarda en busqueda.criterios: los criterios aplicados (IA + filtros de la
    pantalla) y, aparte en "_ia", lo que entendió la IA del texto, que sirve de caché."""
    datos = finales.a_json()
    if i is not None and i.interpretado and texto.strip():
        datos.update(_ia=i.criterios.a_json(), _version=ver, _texto=texto_normalizado(texto))
    elif i is not None and not i.interpretado:
        datos.update(_sin_ia=True)
    return datos


# --------------------------------------------------------------------------- principal
def interpretar(
    conn: psycopg.Connection,
    texto: str,
    catalogo: list[Atributo],
    cliente: ClienteIA | None,
) -> Interpretacion:
    """Nunca lanza por culpa de la IA: si no responde, devuelve interpretado=False."""
    texto = (texto or "").strip()[:MAX_TEXTO]
    ver = version(catalogo)
    if not texto:
        return Interpretacion(Criterios(), interpretado=True)

    guardado = desde_cache(conn, texto, ver)
    if guardado is not None:
        return Interpretacion(guardado, interpretado=True, desde_cache=True)

    if cliente is None:
        return Interpretacion(
            Criterios(), interpretado=False,
            aviso="La IA no está configurada: se buscó por palabras.",
        )
    try:
        respuesta = cliente.completar(instrucciones(catalogo), f"Búsqueda: {texto}")
        datos = leer_json(respuesta.texto)
        criterios, ignorado = validar_criterios(datos, catalogo, mapa_comunas(conn))
    except (ErrorProveedor, LimiteExcedido, RespuestaInvalida) as e:
        log.warning("No se pudo interpretar la búsqueda: %s", e)
        return Interpretacion(
            Criterios(), interpretado=False,
            aviso="No se pudo interpretar la búsqueda con IA: se buscó por palabras.",
        )
    return Interpretacion(criterios, interpretado=True, ignorado=ignorado)


def resumen_legible(c: Criterios, nombres_atributos: dict[str, str],
                    nombres_comunas: dict[str, str]) -> list[str]:
    """Frases cortas para mostrar en la web lo que se entendió (RNF-04)."""
    partes = []
    if c.tipo_propiedad:
        partes.append(c.tipo_propiedad.capitalize())
    if c.operacion:
        partes.append(f"en {c.operacion}")
    if c.comunas:
        partes.append(", ".join(nombres_comunas.get(s, s) for s in c.comunas))
    if c.dormitorios_min:
        partes.append(f"{c.dormitorios_min}+ dormitorios")
    if c.banos_min:
        partes.append(f"{c.banos_min}+ baños")
    if c.m2_min:
        partes.append(f"desde {c.m2_min:.0f} m²")

    def plata(v: Decimal) -> str:
        if c.moneda == "UF":
            return f"UF {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"${v:,.0f}".replace(",", ".")

    if c.precio_min and c.precio_max:
        partes.append(f"entre {plata(c.precio_min)} y {plata(c.precio_max)}")
    elif c.precio_max:
        partes.append(f"hasta {plata(c.precio_max)}")
    elif c.precio_min:
        partes.append(f"desde {plata(c.precio_min)}")
    for codigo, valor in c.atributos.items():
        nombre = nombres_atributos.get(codigo, codigo)
        if valor is True:
            partes.append(nombre)
        elif valor is False:
            partes.append(f"sin {nombre.lower()}")
        elif codigo == "gastos_comunes_clp":
            partes.append(f"gastos comunes hasta ${Decimal(valor):,.0f}".replace(",", "."))
        else:
            partes.append(f"{nombre}: {valor}")
    return partes


def json_seguro(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)
