"""Precisión@10 (PT-007, meta >= 80%) y tiempo de respuesta (PT-014, meta: 95% en < 3 s)
de las búsquedas de validación (EDT 3.2.3: 20 búsquedas).

Uso (desde la raíz; DATABASE_URL apuntando a la base con los 3 portales, ej. Neon):
  1) python scripts/evaluar_busquedas.py generar busquedas.txt --salida p10.csv
       busquedas.txt: una búsqueda por línea, ej. "depto en Ñuñoa que acepte perros"
       Corre cada búsqueda igual que la web (mismo código que /buscar), la marca como de
       validación y deja en p10.csv sus 10 primeros resultados con la columna "relevante".
  2) Llenar "relevante" con si / no mirando cada aviso (abrir la url).
  3) python scripts/evaluar_busquedas.py calcular p10.csv
       Guarda las marcas en la base y calcula la Precisión@10 de cada búsqueda y el promedio.
"""

import argparse
import csv
import io
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from core.db import conectar  # noqa: E402
from core.ia.respuesta import normalizar  # noqa: E402

META_P10 = 0.80
META_MS = 3000
COLUMNAS = ["busqueda_id", "consulta", "posicion", "publicacion_id", "titulo", "comuna",
            "precio_clp", "url", "relevante"]


def leer_consultas(ruta: str) -> list[str]:
    lineas = Path(ruta).read_text(encoding="utf-8-sig").splitlines()
    return [x.strip() for x in lineas if x.strip() and not x.strip().startswith("#")]


def generar(ruta_consultas: str, salida: str) -> None:
    consultas = leer_consultas(ruta_consultas)
    cliente = TestClient(app)
    tiempos = []
    filas = []
    for consulta in consultas:
        inicio = time.perf_counter()
        r = cliente.get("/buscar", params={"q": consulta, "limite": 10})
        ms = round((time.perf_counter() - inicio) * 1000)
        r.raise_for_status()
        datos = r.json()
        tiempos.append(ms)
        with conectar() as conn:
            conn.execute("UPDATE busqueda SET es_validacion = true WHERE id = %s",
                         (datos["busqueda_id"],))
        interp = datos["interpretacion"]
        estado = "IA" if interp["interpretado"] else "palabras"
        print(f"{ms:>5} ms · {datos['total']:>4} resultados · {estado:<8} · {consulta}")
        print(f"          entendido: {', '.join(interp['resumen']) or '(nada)'}")
        for pos, a in enumerate(datos["resultados"], start=1):
            filas.append([datos["busqueda_id"], consulta, pos, a["id"], a["titulo"],
                          a["comuna"] or "", a["precio_clp"] or "", a["url"], ""])

    with open(salida, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(COLUMNAS)
        escritor.writerows(filas)

    rapidas = sum(1 for t in tiempos if t < META_MS)
    print(f"\n{len(consultas)} búsquedas · {len(filas)} resultados en {salida}")
    if tiempos:
        print(f"Tiempo (PT-014): {rapidas}/{len(tiempos)} en < 3 s "
              f"({100 * rapidas / len(tiempos):.0f}%, meta 95%) · máximo {max(tiempos)} ms")
    print('Siguiente paso: llenar "relevante" con si / no y correr el modo "calcular".')


def calcular(ruta: str) -> None:
    contenido = Path(ruta).read_text(encoding="utf-8-sig")
    try:
        dialecto = csv.Sniffer().sniff(contenido[:5000], delimiters=";,\t")
    except csv.Error:
        dialecto = csv.excel
    marcas: dict[int, dict[int, bool]] = defaultdict(dict)
    consultas: dict[int, str] = {}
    devueltos: dict[int, int] = defaultdict(int)
    sin_marcar = 0
    for fila in csv.DictReader(io.StringIO(contenido), dialect=dialecto):
        try:
            bid, pos = int(fila["busqueda_id"]), int(fila["posicion"])
        except (KeyError, TypeError, ValueError):
            continue
        consultas[bid] = fila.get("consulta", "")
        devueltos[bid] += 1
        valor = normalizar(fila.get("relevante") or "")
        if valor in ("si", "s", "1", "x"):
            marcas[bid][pos] = True
        elif valor in ("no", "n", "0"):
            marcas[bid][pos] = False
        else:
            sin_marcar += 1

    with conectar() as conn:
        for bid, por_pos in marcas.items():
            for pos, relevante in por_pos.items():
                conn.execute(
                    "UPDATE resultado_busqueda SET relevante = %s "
                    "WHERE busqueda_id = %s AND posicion = %s",
                    (relevante, bid, pos),
                )

    if sin_marcar:
        print(f"Ojo: {sin_marcar} resultados sin marcar (cuentan como no relevantes).")
    precisiones = []
    print(f"\n{'P@10':>6}  búsqueda")
    for bid, consulta in consultas.items():
        relevantes = sum(1 for pos, v in marcas[bid].items() if v and pos <= 10)
        p10 = relevantes / 10
        precisiones.append(p10)
        nota = f"  (solo {devueltos[bid]} resultados)" if devueltos[bid] < 10 else ""
        print(f"{100 * p10:>5.0f}%  {consulta}{nota}")
    if precisiones:
        promedio = sum(precisiones) / len(precisiones)
        estado = "CUMPLE" if promedio >= META_P10 else "NO CUMPLE"
        print(f"\nPrecisión@10 promedio: {100 * promedio:.0f}% → {estado} la meta de 80% (PT-007)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="modo", required=True)
    g = sub.add_parser("generar", help="corre las búsquedas y crea el CSV para marcar")
    g.add_argument("consultas")
    g.add_argument("--salida", default="p10.csv")
    c = sub.add_parser("calcular", help="lee el CSV marcado y calcula la Precisión@10")
    c.add_argument("csv")
    args = p.parse_args()
    if args.modo == "generar":
        generar(args.consultas, args.salida)
    else:
        calcular(args.csv)


if __name__ == "__main__":
    main()
