"""Crea un ejecutivo de Aurora (o le cambia la contraseña si el correo ya existe).

Uso (desde la raíz, con el entorno virtual activo):
    python scripts/crear_ejecutivo.py --nombre "Ana Pérez" --email ana@aurora.cl

La contraseña se pide por teclado: así no queda en el historial de la terminal.
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.auth import hashear_password  # noqa: E402
from core.db import conectar  # noqa: E402

LARGO_MINIMO = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea o actualiza un ejecutivo de Aurora")
    parser.add_argument("--nombre", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = getpass.getpass(f"Contraseña (mínimo {LARGO_MINIMO} caracteres): ")
    if len(password) < LARGO_MINIMO:
        sys.exit(f"La contraseña debe tener al menos {LARGO_MINIMO} caracteres.")
    if password != getpass.getpass("Repite la contraseña: "):
        sys.exit("Las contraseñas no coinciden.")

    with conectar() as conn:
        fila = conn.execute(
            "INSERT INTO ejecutivo (nombre, email, password_hash) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET nombre = EXCLUDED.nombre, "
            "password_hash = EXCLUDED.password_hash, activo = true "
            "RETURNING id, (xmax = 0) AS nuevo",
            (args.nombre.strip(), args.email.strip().lower(), hashear_password(password)),
        ).fetchone()
    print(f"Ejecutivo {'creado' if fila['nuevo'] else 'actualizado'} (id {fila['id']}).")


if __name__ == "__main__":
    main()
