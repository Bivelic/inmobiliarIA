"""
Script de inicio.

Ejemplos:
    # solo construir la URL (no hace requests), util para verificar filtros
    python main.py --operation arriendo --type departamento --commune providencia \
        --neighborhood llewellyn-jones --bedrooms 4,x --bathrooms 4,x --price 23,x --currency UF \
        --area 100,x --days 1 --url-only

    # buscar de verdad (2 paginas)
    python main.py --operation arriendo --type departamento --commune providencia --max-pages 2

Rangos: "min,max" (x o vacio = sin limite; un solo numero = valor exacto).
Dependencias: pip install httpx curl_cffi
"""
import argparse
import json
from collections import Counter
from pathlib import Path

from search.SearchFactory import SearchFactory
from models.SearchFilters import SearchFilters


def parse_range(text):
    if text is None:
        return None

    def to_int(v):
        v = v.strip().lower()
        return None if v in ("", "x") else int(v)

    if "," not in text:  # un solo numero = exacto
        n = to_int(text)
        return (n, n)
    lo, hi = text.split(",", 1)
    return (to_int(lo), to_int(hi))


def build_parser():
    p = argparse.ArgumentParser(description="Busqueda de propiedades")
    p.add_argument("--site", default="toctoc", help=f"sitio ({', '.join(SearchFactory.available())})")
    p.add_argument("--operation", required=True, help="venta | arriendo")
    p.add_argument("--type", dest="property_type", required=True, help="departamento | casa | ...")
    p.add_argument("--region", default="metropolitana")
    p.add_argument("--commune")
    p.add_argument("--neighborhood")
    p.add_argument("--bedrooms", help="rango, ej. 2,3 o 4,x")
    p.add_argument("--bathrooms", help="rango")
    p.add_argument("--price", help="rango (requiere --currency)")
    p.add_argument("--currency", help="UF | CLP")
    p.add_argument("--area", help="superficie util en m2, rango")
    p.add_argument("--days", type=int, help="publicado hace como maximo N dias")
    p.add_argument("--max-pages", type=int, default=3)
    p.add_argument("--delay", type=float, help="segundos entre requests")
    p.add_argument("--url-only", action="store_true", help="imprime las URLs y termina, sin requests")
    p.add_argument("--out", default="out/listings.json")
    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        filters = SearchFilters(
            operation=args.operation,
            property_type=args.property_type,
            region=args.region,
            commune=args.commune,
            neighborhood=args.neighborhood,
            bedrooms=parse_range(args.bedrooms),
            bathrooms=parse_range(args.bathrooms),
            price=parse_range(args.price),
            currency=args.currency,
            area_util=parse_range(args.area),
            published_within_days=args.days,
        )
        search = SearchFactory.create(args.site, delay=args.delay)
    except ValueError as e:
        parser.error(str(e))

    if args.url_only:
        for page in (1, 2):
            print(f"pagina {page}: {search.build_url(filters, page)}")
        return

    listings = search.search(filters, max_pages=args.max_pages)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=1), encoding="utf-8")

    flags = Counter(f for l in listings for f in l.flags)
    print(f"{len(listings)} avisos unicos -> {out}")
    print(f"flags: {dict(flags) or 'ninguno'}")
    for l in listings[:5]:
        print(f"  {l.commune} | UF {l.price_uf} | ${l.price_clp} | {l.area_m2} m2 | dorm={l.bedrooms} | {l.title[:45]}")


if __name__ == "__main__":
    main()
