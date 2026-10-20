"""Crea las tablas y carga los datos iniciales en la base de DATABASE_URL.

Uso (desde la raíz del repositorio, con el entorno virtual activo):
    python scripts/init_db.py           # crea todo si la base está vacía
    python scripts/init_db.py --reset   # BORRA todo y lo vuelve a crear

Sirve para Neon y para cualquier PostgreSQL. Con Docker no hace falta:
el contenedor carga los mismos archivos la primera vez que se levanta.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import RAIZ  # noqa: E402
from core.db import conectar  # noqa: E402

ARCHIVOS = ["01_schema.sql", "02_comunas.sql", "03_portales_extra.sql"]


def main() -> None:
    reset = "--reset" in sys.argv
    with conectar(autocommit=True) as conn:
        existe = conn.execute("SELECT to_regclass('public.publicacion') AS t").fetchone()["t"]
        if existe and not reset:
            # Las tablas ya están: solo se cargan los datos iniciales nuevos (no duplican nada)
            for nombre in ARCHIVOS[1:]:
                conn.execute((RAIZ / "db" / nombre).read_text(encoding="utf-8"))
                print(f"OK  {nombre}")
            print("La base ya tenía las tablas; datos iniciales al día (--reset para recrearla).")
            return
        if reset:
            respuesta = input("Esto BORRA todos los datos de la base. Escribe 'si' para seguir: ")
            if respuesta.strip().lower() != "si":
                print("Cancelado.")
                return
            conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            print("Base vaciada.")
        for nombre in ARCHIVOS:
            sql = (RAIZ / "db" / nombre).read_text(encoding="utf-8")
            conn.execute(sql)
            print(f"OK  {nombre}")
    print("Listo. Ahora corre: python scripts/check_setup.py")


if __name__ == "__main__":
    main()
