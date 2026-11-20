"""Compara la extracción de la IA con el conjunto de validación etiquetado a mano.

Uso (desde la raíz):
    python scripts/evaluar_extraccion.py validacion.csv            # tabla de precisión
    python scripts/evaluar_extraccion.py validacion.csv --detalle  # además, cada error
    python scripts/evaluar_extraccion.py validacion.csv --guardar  # copia las etiquetas a la base

Antes hay que extraer esos avisos:  python scripts/extraer_atributos.py --csv validacion.csv
Criterio de aceptación de 4.3 (EDT): precisión >= 80%.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import conectar  # noqa: E402
from core.ia.catalogo import cargar_catalogo  # noqa: E402
from core.ia.evaluacion import (  # noqa: E402
    comparar,
    guardar_etiquetas,
    ids_con_extraccion,
    ids_existentes,
    iguales,
    leer_etiquetas,
    predicciones_ia,
    total,
)
from core.ia.prompt import version_prompt  # noqa: E402

META = 0.80


def pct(valor: float | None) -> str:
    return "—" if valor is None else f"{100 * valor:.0f}%"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("csv", help="CSV de etiquetas (de plantilla_etiquetado.py)")
    p.add_argument("--detalle", action="store_true", help="lista cada valor inventado o distinto")
    p.add_argument("--guardar", action="store_true", help="copia las etiquetas a etiqueta_manual")
    args = p.parse_args()

    with conectar(autocommit=True) as conn:
        catalogo = cargar_catalogo(conn)
        tipos = {a.codigo: a.tipo_dato for a in catalogo}
        etiquetas = leer_etiquetas(Path(args.csv), catalogo)

        if etiquetas.errores:
            print(f"Ojo: {len(etiquetas.errores)} celdas con formato inválido (se ignoran):")
            for e in etiquetas.errores[:10]:
                print("  ", e)
        if etiquetas.columnas_desconocidas:
            print("Columnas que no están en el catálogo (se ignoran):",
                  ", ".join(etiquetas.columnas_desconocidas))
        faltan = [a.codigo for a in catalogo if a.codigo not in etiquetas.codigos]
        if faltan:
            print("Atributos del catálogo sin columna en el CSV:", ", ".join(faltan))

        existentes = ids_existentes(conn, etiquetas.ids)
        no_estan = [i for i in etiquetas.ids if i not in existentes]
        if no_estan:
            print(f"Ojo: {len(no_estan)} avisos del CSV no están en esta base "
                  "(¿se etiquetaron con otra base, local vs Neon?)")

        version = version_prompt(catalogo)
        con_extraccion = ids_con_extraccion(conn, sorted(existentes), version)
        sin_extraccion = existentes - con_extraccion
        if sin_extraccion:
            print(f"{len(sin_extraccion)} avisos aún sin extraer con el prompt {version}. Corre:\n"
                  f"   python scripts/extraer_atributos.py --csv {args.csv}")

        ids = sorted(con_extraccion)
        predicciones = predicciones_ia(conn, ids)
        metricas = comparar(etiquetas.valores, predicciones, ids, tipos)

        if args.guardar:
            n = guardar_etiquetas(conn, etiquetas, catalogo)
            print(f"{n} etiquetas copiadas a etiqueta_manual.")

        if args.detalle and ids:
            evidencias = {
                (f["publicacion_id"], f["codigo"]): f["evidencia"]
                for f in conn.execute(
                    "SELECT pa.publicacion_id, a.codigo, pa.evidencia FROM publicacion_atributo pa "
                    "JOIN atributo a ON a.id = pa.atributo_id "
                    "WHERE pa.fuente = 'ia' AND pa.publicacion_id = ANY(%s)",
                    (ids,),
                ).fetchall()
            }
            print("\nDiferencias (aviso · atributo · etiqueta → IA · evidencia de la IA):")
            for pid in ids:
                for codigo in etiquetas.codigos:
                    e = etiquetas.valores.get((pid, codigo))
                    ia = predicciones.get((pid, codigo))
                    if e is None and ia is None:
                        continue
                    if e is not None and ia is not None and iguales(tipos[codigo], e, ia):
                        continue
                    print(f"  {pid:>6} · {codigo:<18} · {e if e is not None else '(vacío)'!s:>9}"
                          f" → {ia if ia is not None else '(no lo encontró)'!s:<16} · "
                          f"{(evidencias.get((pid, codigo)) or '')[:60]}")

    print(f"\nEvaluados: {len(ids)} avisos · prompt {version}\n")
    print(f"{'atributo':<20}{'etiq.':>6}{'IA':>6}{'OK':>6}{'dist.':>6}{'inv.':>6}{'omit.':>6}"
          f"{'precisión':>11}{'cobertura':>11}")
    for codigo in etiquetas.codigos:
        m = metricas.get(codigo)
        if m is None:
            continue
        print(f"{codigo:<20}{m.etiquetados:>6}{m.predichos:>6}{m.aciertos:>6}"
              f"{m.valor_distinto:>6}{m.inventados:>6}{m.omitidos:>6}"
              f"{pct(m.precision):>11}{pct(m.cobertura):>11}")
    t = total(metricas)
    print("-" * 78)
    print(f"{'TOTAL':<20}{t.etiquetados:>6}{t.predichos:>6}{t.aciertos:>6}{t.valor_distinto:>6}"
          f"{t.inventados:>6}{t.omitidos:>6}{pct(t.precision):>11}{pct(t.cobertura):>11}")
    print("\netiq. = la etiqueta tiene valor · IA = la IA informó valor · dist. = valor distinto ·"
          "\ninv. = la IA informó algo que el aviso no menciona · omit. = la IA no lo encontró")
    if t.precision is not None:
        estado = "CUMPLE" if t.precision >= META else "NO CUMPLE"
        print(f"\nPrecisión total {pct(t.precision)} → {estado} la meta de {pct(META)} (EDT 4.3)")


if __name__ == "__main__":
    main()
