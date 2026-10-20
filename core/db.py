"""Conexión a PostgreSQL con psycopg 3."""

from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from core.config import database_url


def conectar(**kwargs) -> psycopg.Connection:
    """Abre una conexión nueva. Las filas se devuelven como diccionarios."""
    return psycopg.connect(database_url(), row_factory=dict_row, **kwargs)


@contextmanager
def conexion():
    """Uso: `with conexion() as conn: conn.execute(...)`.
    Hace commit al salir sin errores y rollback si algo falla."""
    conn = conectar()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
