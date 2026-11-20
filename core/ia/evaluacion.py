"""Medición de la extracción contra el conjunto de validación etiquetado a mano (EDT 3.2.3 / 5.3.3).

Las etiquetas vienen en un CSV (el que genera scripts/plantilla_etiquetado.py), con una fila por
aviso y una columna por atributo:
  - booleano: "si" / "no" / vacío (vacío = el aviso no lo menciona)
  - numero:   el número (ej. 85000 o 85.000) / vacío
  - texto:    el texto (ej. Los Leones) / vacío

Por atributo y en total se calcula:
  - precisión  = aciertos / valores que informó la IA      (criterio de aceptación de 4.3: >= 80%)
  - cobertura  = aciertos / valores que dicen las etiquetas (cuánto de lo mencionado encuentra)
  - inventados = la IA informó algo que el aviso no menciona (RF-03.06)
"""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import psycopg

from core.ia.catalogo import Atributo
from core.ia.respuesta import normalizar
from core.normalizacion import numero

COLUMNAS_FIJAS = ["publicacion_id", "portal", "url", "titulo", "descripcion"]
COLUMNAS_FINALES = ["etiquetado_por", "notas"]
_SI = {"si", "s", "1", "true", "x", "yes"}
_NO = {"no", "n", "0", "false"}

Valor = bool | Decimal | str


@dataclass
class Etiquetas:
    valores: dict[tuple[int, str], Valor | None] = field(default_factory=dict)
    autores: dict[int, str] = field(default_factory=dict)
    codigos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)
    columnas_desconocidas: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[int]:
        return list(self.autores)


@dataclass
class Metrica:
    etiquetados: int = 0  # celdas donde la etiqueta tiene valor
    predichos: int = 0  # celdas donde la IA informó valor
    aciertos: int = 0
    valor_distinto: int = 0
    inventados: int = 0
    omitidos: int = 0
    ambos_vacios: int = 0

    @property
    def precision(self) -> float | None:
        return self.aciertos / self.predichos if self.predichos else None

    @property
    def cobertura(self) -> float | None:
        return self.aciertos / self.etiquetados if self.etiquetados else None

    def sumar(self, otra: "Metrica") -> None:
        for campo in self.__dataclass_fields__:
            setattr(self, campo, getattr(self, campo) + getattr(otra, campo))


# --------------------------------------------------------------------------- CSV
def leer_valor(tipo: str, celda: str) -> Valor | None:
    texto = (celda or "").strip()
    if not texto:
        return None
    if tipo == "booleano":
        n = normalizar(texto)
        if n in _SI:
            return True
        if n in _NO:
            return False
        raise ValueError(f'se esperaba "si", "no" o vacío y dice "{texto}"')
    if tipo == "numero":
        valor = numero(texto)
        if valor is None:
            raise ValueError(f'se esperaba un número y dice "{texto}"')
        return valor
    return texto


def leer_etiquetas(ruta: Path, catalogo: list[Atributo]) -> Etiquetas:
    contenido = ruta.read_text(encoding="utf-8-sig")
    try:
        dialecto = csv.Sniffer().sniff(contenido[:5000], delimiters=";,\t")
    except csv.Error:
        dialecto = csv.excel
    lector = csv.DictReader(io.StringIO(contenido), dialect=dialecto)
    tipos = {a.codigo: a.tipo_dato for a in catalogo}
    columnas = [c.strip() for c in (lector.fieldnames or [])]
    if "publicacion_id" not in columnas:
        raise ValueError("El CSV no tiene la columna publicacion_id")

    resultado = Etiquetas()
    resultado.codigos = [c for c in columnas if c in tipos]
    resultado.columnas_desconocidas = [
        c for c in columnas if c not in tipos and c not in COLUMNAS_FIJAS + COLUMNAS_FINALES
    ]
    for n_fila, fila in enumerate(lector, start=2):
        fila = {(k or "").strip(): v for k, v in fila.items()}
        try:
            pid = int(str(fila.get("publicacion_id", "")).strip())
        except ValueError:
            if any((v or "").strip() for v in fila.values()):
                resultado.errores.append(f"fila {n_fila}: publicacion_id inválido")
            continue
        resultado.autores[pid] = (fila.get("etiquetado_por") or "").strip() or "sin_nombre"
        for codigo in resultado.codigos:
            try:
                resultado.valores[(pid, codigo)] = leer_valor(tipos[codigo], fila.get(codigo, ""))
            except ValueError as e:
                resultado.errores.append(f"fila {n_fila}, {codigo}: {e}")
    return resultado


# --------------------------------------------------------------------------- comparación
def iguales(tipo: str, etiqueta: Valor, ia: Valor) -> bool:
    if tipo == "booleano":
        return bool(etiqueta) == bool(ia)
    if tipo == "numero":
        e, p = Decimal(str(etiqueta)), Decimal(str(ia))
        return abs(e - p) <= max(Decimal(1), abs(e) * Decimal("0.01"))
    a, b = normalizar(str(etiqueta)), normalizar(str(ia))
    return a == b or (len(a) >= 3 and len(b) >= 3 and (a in b or b in a))


def comparar(
    etiquetas: dict[tuple[int, str], Valor | None],
    predicciones: dict[tuple[int, str], Valor],
    ids: list[int],
    tipos: dict[str, str],
) -> dict[str, Metrica]:
    """Métrica por código de atributo. Solo considera los avisos de `ids`."""
    por_codigo: dict[str, Metrica] = defaultdict(Metrica)
    codigos = sorted({c for (_, c) in etiquetas})
    for pid in ids:
        for codigo in codigos:
            m = por_codigo[codigo]
            etiqueta = etiquetas.get((pid, codigo))
            ia = predicciones.get((pid, codigo))
            if etiqueta is not None:
                m.etiquetados += 1
            if ia is not None:
                m.predichos += 1
            if etiqueta is None and ia is None:
                m.ambos_vacios += 1
            elif etiqueta is None:
                m.inventados += 1
            elif ia is None:
                m.omitidos += 1
            elif iguales(tipos[codigo], etiqueta, ia):
                m.aciertos += 1
            else:
                m.valor_distinto += 1
    return dict(por_codigo)


def total(metricas: dict[str, Metrica]) -> Metrica:
    t = Metrica()
    for m in metricas.values():
        t.sumar(m)
    return t


# --------------------------------------------------------------------------- base de datos
def predicciones_ia(conn: psycopg.Connection, ids: list[int]) -> dict[tuple[int, str], Valor]:
    filas = conn.execute(
        """
        SELECT pa.publicacion_id, a.codigo, pa.valor_bool, pa.valor_num, pa.valor_texto
        FROM publicacion_atributo pa JOIN atributo a ON a.id = pa.atributo_id
        WHERE pa.fuente = 'ia' AND pa.publicacion_id = ANY(%s)
        """,
        (ids,),
    ).fetchall()
    resultado = {}
    for f in filas:
        valores = (f["valor_bool"], f["valor_num"], f["valor_texto"])
        resultado[(f["publicacion_id"], f["codigo"])] = next(v for v in valores if v is not None)
    return resultado


def ids_con_extraccion(conn: psycopg.Connection, ids: list[int], version: str) -> set[int]:
    filas = conn.execute(
        "SELECT DISTINCT publicacion_id FROM extraccion_ia "
        "WHERE exitosa AND version_prompt = %s AND publicacion_id = ANY(%s)",
        (version, ids),
    ).fetchall()
    return {f["publicacion_id"] for f in filas}


def ids_existentes(conn: psycopg.Connection, ids: list[int]) -> set[int]:
    filas = conn.execute("SELECT id FROM publicacion WHERE id = ANY(%s)", (ids,)).fetchall()
    return {f["id"] for f in filas}


def guardar_etiquetas(
    conn: psycopg.Connection, etiquetas: Etiquetas, catalogo: list[Atributo]
) -> int:
    """Copia las etiquetas a la tabla etiqueta_manual (reemplaza las de esos avisos).
    Las celdas vacías ("no lo menciona") no se guardan: la tabla solo admite valores."""
    ids_atributo = {a.codigo: a.id for a in catalogo}
    tipos = {a.codigo: a.tipo_dato for a in catalogo}
    existentes = ids_existentes(conn, etiquetas.ids)
    n = 0
    with conn.transaction():
        for pid in existentes:
            conn.execute("DELETE FROM etiqueta_manual WHERE publicacion_id = %s", (pid,))
        for (pid, codigo), valor in etiquetas.valores.items():
            if valor is None or pid not in existentes:
                continue
            tipo = tipos[codigo]
            conn.execute(
                """
                INSERT INTO etiqueta_manual (publicacion_id, atributo_id, valor_bool, valor_num,
                                             valor_texto, etiquetado_por)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    pid,
                    ids_atributo[codigo],
                    valor if tipo == "booleano" else None,
                    valor if tipo == "numero" else None,
                    valor if tipo == "texto" else None,
                    etiquetas.autores.get(pid, "sin_nombre"),
                ),
            )
            n += 1
    return n
