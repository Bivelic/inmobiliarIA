"""Muestra, por portal, cuántos avisos hay en la base y cómo resultó la última ejecución.
    python scripts/resumen.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import conectar  # noqa: E402

SQL = """
SELECT po.codigo AS portal,
       (SELECT count(*) FROM publicacion p WHERE p.portal_id = po.id AND p.activa) AS activos,
       u.id AS ejecucion, u.estado, u.avisos_leidos AS leidos, u.avisos_ok AS ok,
       round(100.0 * u.avisos_ok / NULLIF(u.avisos_leidos, 0), 1) AS pct
FROM portal po
LEFT JOIN LATERAL (SELECT * FROM ejecucion_scraping e WHERE e.portal_id = po.id
                   ORDER BY e.inicio DESC LIMIT 1) u ON true
ORDER BY po.id
"""

with conectar() as conn:
    filas = conn.execute(SQL).fetchall()
    errores = conn.execute(
        "SELECT po.codigo AS portal, er.tipo, er.mensaje "
        "FROM error_scraping er JOIN ejecucion_scraping e ON e.id = er.ejecucion_id "
        "JOIN portal po ON po.id = e.portal_id ORDER BY er.id DESC LIMIT 5"
    ).fetchall()

print(f"{'portal':<18}{'activos':>8}  {'última ejecución':<22}{'sin error':>10}")
for f in filas:
    ultima = f"#{f['ejecucion']} {f['estado']}" if f["ejecucion"] else "nunca"
    pct = f"{f['pct']}% ({f['ok']}/{f['leidos']})" if f["leidos"] else "-"
    print(f"{f['portal']:<18}{f['activos']:>8}  {ultima:<22}{pct:>10}")

if errores:
    print("\nÚltimos errores:")
    for e in errores:
        mensaje = " ".join((e["mensaje"] or "").split())[:100]
        print(f"  [{e['portal']}] {e['tipo']}: {mensaje}")
