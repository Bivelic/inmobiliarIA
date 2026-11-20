"""Catálogo de atributos a detectar (tabla `atributo`, cargada desde db/04_atributos.sql)."""

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Atributo:
    id: int
    codigo: str
    nombre: str
    tipo_dato: str  # 'booleano' | 'numero' | 'texto'
    descripcion: str


def cargar_catalogo(conn: psycopg.Connection) -> list[Atributo]:
    filas = conn.execute(
        "SELECT id, codigo, nombre, tipo_dato::text AS tipo_dato, descripcion "
        "FROM atributo ORDER BY id"
    ).fetchall()
    if not filas:
        raise RuntimeError(
            "La tabla atributo está vacía. Corre: python scripts/init_db.py "
            "(carga db/04_atributos.sql)."
        )
    return [Atributo(**f) for f in filas]
