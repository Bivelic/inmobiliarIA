"""Extrae con IA los atributos de los avisos pendientes y los guarda en la base (EDT 4.3).

Uso (desde la raíz, con el entorno virtual activo y las claves en el .env):
    python scripts/extraer_atributos.py --ver-prompt          # muestra el prompt; NO llama a la IA
    python scripts/extraer_atributos.py --limite 20           # prueba corta
    python scripts/extraer_atributos.py --limite 500          # corrida grande (puede tardar)
    python scripts/extraer_atributos.py --csv validacion.csv  # solo el conjunto de validación
    python scripts/extraer_atributos.py --ids 12,15 --forzar  # reprocesa avisos puntuales

Un aviso ya procesado no se vuelve a mandar mientras no cambie su texto ni el prompt,
así que se puede correr las veces que haga falta sin gastar de más.
"""

import argparse
import csv
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import conectar  # noqa: E402
from core.ia.catalogo import cargar_catalogo  # noqa: E402
from core.ia.extraccion import Extractor, avisos_pendientes  # noqa: E402
from core.ia.prompt import instrucciones, mensaje_lote, version_prompt  # noqa: E402
from core.ia.proveedores import ClienteIA, crear_proveedores  # noqa: E402


def ids_de_csv(ruta: str) -> list[int]:
    contenido = Path(ruta).read_text(encoding="utf-8-sig")
    try:
        dialecto = csv.Sniffer().sniff(contenido[:5000], delimiters=";,\t")
    except csv.Error:
        dialecto = csv.excel
    ids = []
    for fila in csv.DictReader(io.StringIO(contenido), dialect=dialecto):
        valor = str(fila.get("publicacion_id") or "").strip()
        if valor.isdigit():
            ids.append(int(valor))
    return ids


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--limite", type=int, default=100, help="máximo de avisos en esta corrida")
    p.add_argument("--lote", type=int, default=5, help="avisos por llamada a la IA")
    p.add_argument("--pausa", type=float, default=2.0, help="segundos entre llamadas")
    p.add_argument("--ids", help="ids de publicaciones separados por coma")
    p.add_argument("--csv", help="CSV con columna publicacion_id (ej. el de validación)")
    p.add_argument("--forzar", action="store_true", help="reprocesa aunque ya estén procesados")
    p.add_argument("--proveedores", help="ej. groq o gemini,groq (por defecto IA_PROVEEDORES)")
    p.add_argument("--ver-prompt", action="store_true", help="muestra el prompt de un lote y sale")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ids = None
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.csv:
        ids = ids_de_csv(args.csv)
        print(f"{len(ids)} avisos leídos de {args.csv}")
    limite = max(args.limite, len(ids)) if ids else args.limite

    with conectar(autocommit=True) as conn:
        catalogo = cargar_catalogo(conn)
        version = version_prompt(catalogo)

        if args.ver_prompt:
            pendientes = avisos_pendientes(conn, version, args.lote, ids, forzar=True)
            print("=" * 30, "INSTRUCCIONES (sistema)", "=" * 30)
            print(instrucciones(catalogo))
            print("=" * 30, "MENSAJE (lote de ejemplo)", "=" * 30)
            print(mensaje_lote([x.aviso for x in pendientes]) if pendientes else "(sin avisos)")
            print(f"\nVersión del prompt: {version} · {len(catalogo)} atributos")
            return

        proveedores = args.proveedores.split(",") if args.proveedores else None
        try:
            cliente = ClienteIA(crear_proveedores(proveedores))
        except RuntimeError as e:
            sys.exit(f"Error: {e}")
        print("Proveedores:", ", ".join(f"{x.nombre} ({x.modelo})" for x in cliente.proveedores))
        extractor = Extractor(conn, cliente, catalogo, pausa=args.pausa)
        r = extractor.correr(limite=limite, tamano_lote=args.lote, ids=ids, forzar=args.forzar)
        quedan = len(avisos_pendientes(conn, version, 10**9))

    print()
    print(f"Versión del prompt:     {r.version_prompt}")
    print(f"Avisos en esta corrida: {r.pendientes}")
    print(f"  procesados OK:        {r.exitosos}")
    print(f"  con error:            {r.fallidos}")
    print(f"Atributos guardados:    {r.valores_guardados}")
    print(f"Atributos descartados:  {r.descartados}")
    for motivo, n in r.motivos_descarte.most_common(5):
        print(f"  {n:>4} × {motivo}")
    print(f"Llamadas a la IA:       {r.llamadas} ({dict(r.por_modelo)})")
    print(f"Tokens:                 {r.tokens_entrada} entrada / {r.tokens_salida} salida")
    print(f"Costo equivalente pago: USD {r.costo_usd:.4f} (en plan gratuito: USD 0)")
    print(f"Avisos pendientes:      {quedan}")
    if r.detenido_por:
        print(f"\nLa corrida se detuvo antes de terminar: {r.detenido_por}")
        sys.exit(1)


if __name__ == "__main__":
    main()
