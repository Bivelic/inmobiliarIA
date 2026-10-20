"""Verifica que el entorno esté listo para trabajar. Corre desde la raíz:
    python scripts/check_setup.py
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, MAL = "[OK]  ", "[FALTA]"
errores = 0


def revisar(descripcion: str, funcion) -> None:
    global errores
    try:
        detalle = funcion()
        print(f"{OK} {descripcion}" + (f": {detalle}" if detalle else ""))
    except Exception as e:  # noqa: BLE001
        errores += 1
        print(f"{MAL} {descripcion}: {e}")


def python_ok():
    v = sys.version_info
    if v < (3, 11):
        raise RuntimeError(f"tienes Python {v.major}.{v.minor}; se necesita 3.11 o más")
    return f"{v.major}.{v.minor}.{v.micro}"


def paquetes_ok():
    for p in ["scrapy", "pydantic", "psycopg", "fastapi", "dotenv"]:
        importlib.import_module(p)
    return "scrapy, pydantic, psycopg, fastapi, python-dotenv"


def env_ok():
    from core.config import database_url

    url = database_url()
    return url.split("@")[-1].split("?")[0]  # muestra host/base sin la clave


def base_ok():
    from core.db import conectar

    with conectar() as conn:
        version = conn.execute("SHOW server_version").fetchone()["server_version"]
        return f"PostgreSQL {version}"


def tablas_ok():
    from core.db import conectar

    esperadas = {"portal", "comuna", "publicacion", "ejecucion_scraping", "error_scraping"}
    with conectar() as conn:
        filas = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ).fetchall()
        faltan = esperadas - {f["table_name"] for f in filas}
        if faltan:
            raise RuntimeError(f"faltan {sorted(faltan)}; corre python scripts/init_db.py")
        portales = conn.execute("SELECT count(*) AS n FROM portal").fetchone()["n"]
        comunas = conn.execute("SELECT count(*) AS n FROM comuna").fetchone()["n"]
        return f"{len(filas)} tablas, {portales} portales, {comunas} comunas"


revisar("Python", python_ok)
revisar("Paquetes instalados", paquetes_ok)
revisar("Archivo .env con DATABASE_URL", env_ok)
revisar("Conexión a la base", base_ok)
revisar("Tablas y datos iniciales", tablas_ok)

print()
if errores:
    print(f"Hay {errores} problema(s). Revisa la sección 'Problemas comunes' del README.")
    sys.exit(1)
print("Todo listo para empezar a programar.")
