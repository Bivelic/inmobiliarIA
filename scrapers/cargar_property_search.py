"""Guarda en nuestra base los avisos que obtiene property_search.

property_search/ se usa tal cual, sin modificarlo. Este archivo solo:
  1. arma los filtros con los mismos argumentos que property_search/main.py,
  2. descarga con acceso honesto (User-Agent del proyecto y robots.txt respetado),
  3. convierte cada Listing a nuestro formato común y lo guarda con core/guardado.py.

Uso (desde la raíz del repositorio, con el entorno virtual activo):
    python scrapers/cargar_property_search.py --operation arriendo --type departamento --max-pages 2
    python scrapers/cargar_property_search.py --operation arriendo --type departamento --url-only
"""

import importlib.util
import sys
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

RAIZ = Path(__file__).resolve().parents[1]
CARPETA_PS = RAIZ / "scrapers" / "property_search"
for ruta in (str(RAIZ), str(CARPETA_PS)):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import httpx  # noqa: E402
from models.SearchFilters import SearchFilters  # noqa: E402  (property_search)
from search.SearchFactory import SearchFactory  # noqa: E402  (property_search)

from core.config import scraper_contacto  # noqa: E402
from core.guardado import Ejecucion  # noqa: E402

# main.py de property_search se carga por ruta para reutilizar sus argumentos de línea de comandos
_spec = importlib.util.spec_from_file_location("property_search_main", CARPETA_PS / "main.py")
ps_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps_main)

USER_AGENT = f"InmobiliarIA-bot/0.1 (proyecto academico IIC3113; contacto: {scraper_contacto()})"
HEADERS_HONESTOS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "es-CL,es;q=0.9",
}


# ---------------------------------------------------------------------- descarga
class DescargaHonesta:
    """Reemplaza el fetch() de property_search: se identifica como bot y respeta robots.txt."""

    def __init__(self):
        self.paginas = 0
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    def permitido(self, url: str) -> bool:
        partes = urlsplit(url)
        sitio = f"{partes.scheme}://{partes.netloc}"
        if sitio not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = httpx.get(f"{sitio}/robots.txt", headers=HEADERS_HONESTOS, timeout=15)
                if r.status_code in (401, 403):
                    rp.disallow_all = True  # el sitio nos niega incluso robots.txt
                elif r.status_code >= 400:
                    rp.allow_all = True  # no hay robots.txt: no hay reglas
                else:
                    rp.parse(r.text.splitlines())
            except httpx.HTTPError:
                rp.disallow_all = True  # sin poder leer las reglas, no se scrapea
            self._robots[sitio] = rp
        return self._robots[sitio].can_fetch(USER_AGENT, url)

    def __call__(self, url: str) -> tuple[int, str]:
        if not self.permitido(url):
            return 403, ""  # bloqueado por robots.txt: se trata como una página negada
        self.paginas += 1
        with httpx.Client(headers=HEADERS_HONESTOS, follow_redirects=True, timeout=30) as c:
            r = c.get(url)
            return r.status_code, r.text


# ---------------------------------------------------------------------- mapeo
def _decimal(valor) -> Decimal | None:
    return Decimal(str(valor)) if valor is not None else None


def _uno(valores: list[int]) -> int | None:
    """Dormitorios y baños vienen en lista; en proyectos con varias tipologías se toma el menor."""
    return min(valores) if valores else None


def listing_a_aviso(listing, url_base: str = "") -> dict:
    """Convierte un Listing de property_search al formato de AvisoNormalizado.

    Lo que no se guarda: `broker` (dato del publicante) y `flags` (se informan al final).
    `area_m2` se guarda como superficie útil, igual que el filtro 'superficie-util' de TocToc.
    """
    solo_uf = listing.price_uf and not listing.price_clp
    moneda = listing.price_currency or ("UF" if solo_uf else "CLP")
    monto = listing.price_uf if moneda == "UF" else listing.price_clp
    fecha = None
    if listing.hours_published is not None:
        fecha = (datetime.now() - timedelta(hours=listing.hours_published)).date()
    return {
        "portal": listing.source,
        "id_externo": str(listing.listing_id or ""),
        "url": urljoin(url_base, listing.url or ""),
        "operacion": (listing.operation or "").strip().lower(),
        "tipo_propiedad": (listing.property_type or "").strip().lower(),
        "titulo": listing.title,
        "descripcion": listing.description,
        "precio_monto": _decimal(monto),
        "precio_moneda": moneda,
        "precio_clp": _decimal(listing.price_clp),
        "precio_uf": _decimal(round(listing.price_uf, 2)) if listing.price_uf else None,
        "comuna": listing.commune,
        "latitud": _decimal(listing.lat),
        "longitud": _decimal(listing.lon),
        "dormitorios": _uno(listing.bedrooms),
        "banos": _uno(listing.bathrooms),
        "m2_util": _decimal(listing.area_m2),
        "fecha_publicacion": fecha,
    }


# ---------------------------------------------------------------------- ejecución
def main():
    parser = ps_main.build_parser()
    parser.description = "Busca con property_search y guarda los avisos en la base"
    parser.add_argument(
        "--marcar-bajas", action="store_true",
        help="la búsqueda cubrió todo el portal: marca inactivos los avisos no vistos hoy",
    )
    args = parser.parse_args()
    r = ps_main.parse_range
    filtros = SearchFilters(
        operation=args.operation, property_type=args.property_type, region=args.region,
        commune=args.commune, neighborhood=args.neighborhood,
        bedrooms=r(args.bedrooms), bathrooms=r(args.bathrooms), price=r(args.price),
        currency=args.currency, area_util=r(args.area), published_within_days=args.days,
    )
    buscador = SearchFactory.create(args.site, delay=args.delay)
    descarga = DescargaHonesta()
    #buscador.fetch = descarga

    if args.url_only:
        for pagina in (1, 2):
            print(f"pagina {pagina}: {buscador.build_url(filtros, pagina)}")
        return

    ejecucion = Ejecucion(buscador.name)
    print(f"Ejecución {ejecucion.id} iniciada ({buscador.name})")
    terminada = True
    try:
        listings = buscador.search(filtros, max_pages=args.max_pages)
    except Exception as e:  # noqa: BLE001 - la primera página falló: se registra y se cierra
        ejecucion.error_sin_aviso(buscador.build_url(filtros, 1), "http", repr(e))
        listings, terminada = [], False

    url_base = getattr(buscador, "BASE", "")
    for listing in listings:
        ejecucion.procesar(listing_a_aviso(listing, url_base))

    print(ejecucion.cerrar(terminada, completa=args.marcar_bajas, paginas=descarga.paginas))
    flags = Counter(f for x in listings for f in x.flags)
    if flags:
        print(f"Avisos de calidad de datos: {dict(flags)}")


if __name__ == "__main__":
    main()
