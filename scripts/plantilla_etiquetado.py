"""Genera el CSV para etiquetar a mano el conjunto de validación de la IA (EDT 3.2.3).

Uso (desde la raíz; DATABASE_URL debe apuntar a la MISMA base donde correrá la IA, ej. Neon):
    python scripts/plantilla_etiquetado.py --n 200 --salida validacion.csv

Elige avisos al azar repartidos por portal (siempre los mismos para la misma --semilla) y
deja una columna vacía por atributo. Se abre con Excel o Google Sheets. En cada celda:
    booleano -> si / no / vacío (vacío = el aviso no lo menciona)
    numero   -> el número (ej. 85000)
    texto    -> el texto (ej. Los Leones)
y en "etiquetado_por" el nombre de quien la llenó. NO hay que cambiar publicacion_id.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import conectar  # noqa: E402
from core.ia.catalogo import cargar_catalogo  # noqa: E402
from core.ia.evaluacion import COLUMNAS_FIJAS, COLUMNAS_FINALES  # noqa: E402
from core.ia.extraccion import MIN_LARGO_DESCRIPCION  # noqa: E402

SQL = """
WITH candidatos AS (
    SELECT p.id, po.codigo AS portal, p.url, p.titulo, p.descripcion,
           row_number() OVER (PARTITION BY po.codigo ORDER BY md5(p.id::text || %(semilla)s))
             AS orden
    FROM publicacion p JOIN portal po ON po.id = p.portal_id
    WHERE p.activa AND p.duplicado_de IS NULL
      AND length(coalesce(p.descripcion, '')) >= %(min_largo)s
)
SELECT id, portal, url, titulo, descripcion FROM candidatos
ORDER BY orden, portal
LIMIT %(n)s
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--n", type=int, default=200, help="cantidad de avisos (EDT 3.2.3: 200)")
    p.add_argument("--salida", default="validacion.csv")
    p.add_argument("--semilla", default="inmobiliaria", help="cambia la muestra")
    args = p.parse_args()

    with conectar() as conn:
        catalogo = cargar_catalogo(conn)
        filas = conn.execute(
            SQL, {"semilla": args.semilla, "min_largo": MIN_LARGO_DESCRIPCION, "n": args.n}
        ).fetchall()

    codigos = [a.codigo for a in catalogo]
    salida = Path(args.salida)
    with salida.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: Excel lee tildes
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(COLUMNAS_FIJAS + codigos + COLUMNAS_FINALES)
        for fila in filas:
            escritor.writerow(
                [fila["id"], fila["portal"], fila["url"], fila["titulo"], fila["descripcion"]]
                + [""] * len(codigos)
                + ["", ""]
            )

    por_portal: dict[str, int] = {}
    for fila in filas:
        por_portal[fila["portal"]] = por_portal.get(fila["portal"], 0) + 1
    print(f"{len(filas)} avisos en {salida} ({por_portal})")
    print("Columnas a llenar:")
    for a in catalogo:
        formato = {"booleano": "si / no / vacío", "numero": "número", "texto": "texto"}[a.tipo_dato]
        print(f"  {a.codigo:<20} {formato:<16} {a.descripcion[:70]}...")
    if len(filas) < args.n:
        print(f"Ojo: la base solo tiene {len(filas)} avisos con descripción.")


if __name__ == "__main__":
    main()
