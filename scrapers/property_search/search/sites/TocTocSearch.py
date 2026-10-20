from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple
from urllib.parse import urlencode

from models.Listing import Listing
from search.PropertySearch import PropertySearch
from models.SearchFilters import Range, SearchFilters

NEXT_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S | re.I)

# Superficie escrita en texto libre: "150 m² útil", "43 m2", "37.00 m²"
_NUM = r"(\d{1,4}(?:[.,]\d{1,3})?)"
_UNIT = r"\s*(?:m2|m²|mt2|mt²|mts2|mts²|mtr2|mtrs2|(?:m|mt|mts|metros)\.?\s*cuadrados)"  # sin "mts"/"metros" sueltos: serian distancias
AREA_UTIL_RE = re.compile(_NUM + _UNIT + r"\s*(?:de\s+)?[uú]til(?:es)?", re.I)
AREA_ANY_RE = re.compile(_NUM + _UNIT, re.I)


class TocTocSearch(PropertySearch):
    """toctoc.com: los avisos vienen en el JSON de __NEXT_DATA__ (sin LLM ni selectores).

    URL:    /{operacion}/{tipo}/{region}/{comuna}/{barrio}?filtros
    Rangos: 'min,max', con 0 = sin minimo y 'x' = sin maximo (ej. dormitorios=4,x).
    Pagina: ?pagina=N (la pagina 1 se pide sin el parametro).
    """

    name = "toctoc"
    BASE = "https://www.toctoc.com"
    MAX_ARRIENDO_CLP = 10_000_000  # sobre esto, un arriendo se marca como outlier
    # currencyType (inferido de los datos, no documentado): 1 = aviso en CLP, 2 = aviso en UF
    CURRENCY_BY_TYPE = {1: "CLP", 2: "UF"}
    AREA_MIN, AREA_MAX = 8, 5000  # rango razonable de m2 para aceptar una superficie sacada del texto

    # ------------------------------------------------------------------ URL
    @staticmethod
    def _range(rng: Range) -> str:
        lo, hi = rng
        return f"{0 if lo is None else lo},{'x' if hi is None else hi}"

    def build_url(self, filters: SearchFilters, page: int = 1) -> str:
        if filters.operation not in ("venta", "arriendo"):
            raise ValueError("toctoc: operation debe ser 'venta' o 'arriendo'")

        segments = [filters.operation, filters.property_type, filters.region, filters.commune, filters.neighborhood]
        path = "/".join(self.slugify(s) for s in segments if s)  # omite los segmentos vacios

        params: List[Tuple[str, object]] = []
        if filters.bedrooms:
            params.append(("dormitorios", self._range(filters.bedrooms)))
        if filters.bathrooms:
            params.append(("bannos", self._range(filters.bathrooms)))
        if filters.price:
            params.append(("precios", self._range(filters.price)))
            params.append(("moneda", filters.currency))
        if filters.area_util:
            params.append(("superficie-util", self._range(filters.area_util)))
        if filters.published_within_days is not None:
            params.append(("fecha-publicacion", filters.published_within_days))
        if page > 1:
            params.append(("pagina", page))

        url = f"{self.BASE}/{path}"
        if params:
            url += "?" + urlencode(params, safe=",")  # las comas van literales, como en el sitio
        return url

    # ------------------------------------------------------------- extraccion
    def extract(self, html: str) -> List[Listing]:
        m = NEXT_RE.search(html)
        if not m:
            raise ValueError("toctoc: no hay __NEXT_DATA__ (pagina bloqueada o cambio de formato)")
        try:
            results = json.loads(m.group(1))["props"]["pageProps"]["propiedades"]["results"]
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            raise ValueError(f"toctoc: estructura inesperada en __NEXT_DATA__ ({e!r})")
        return [self._to_listing(r) for r in results]

    @staticmethod
    def _cl_number(s) -> Optional[float]:
        """'1.600.000' -> 1600000.0 ; '12,5' -> 12.5 ; '' -> None (formato chileno)."""
        if s is None or str(s).strip() == "":
            return None
        try:
            return float(str(s).strip().replace(".", "").replace(",", "."))
        except ValueError:
            return None

    def _positive_ints(self, values) -> List[int]:
        """superficie/dormitorios/banos vienen como lista de strings; '0' = dato faltante."""
        out = []
        for v in values or []:
            n = self._cl_number(v)
            if n is not None and n > 0:
                out.append(int(n))
        return out

    @staticmethod
    def _area_number(txt: str) -> Optional[float]:
        """En texto libre '37.00' es decimal y '1.200' es miles: se distingue por la cantidad de decimales."""
        if re.fullmatch(r"\d{1,2}\.\d{3}", txt):
            return float(txt.replace(".", ""))
        try:
            return float(txt.replace(",", "."))
        except ValueError:
            return None

    def _area_from_text(self, title: str, description: str) -> Optional[int]:
        """Respaldo cuando 'superficie' viene en 0: prioriza '... m² útil', luego cualquier m² del titulo
        y por ultimo de la descripcion."""
        candidates = [
            (AREA_UTIL_RE, f"{title}\n{description}"),
            (AREA_ANY_RE, title),
            (AREA_ANY_RE, description),
        ]
        for regex, text in candidates:
            for m in regex.finditer(text or ""):
                n = self._area_number(m.group(1))
                if n is not None and self.AREA_MIN <= n <= self.AREA_MAX:
                    return int(round(n))
        return None

    def _to_listing(self, r: dict) -> Listing:
        uf = clp = None
        for p in r.get("precios", []):
            if p.get("prefix") == "UF":
                uf = self._cl_number(p.get("value"))
            elif p.get("prefix") == "$":
                clp = self._cl_number(p.get("value"))
        area = self._positive_ints(r.get("superficie"))

        item = Listing(
            source=self.name,
            listing_id=r.get("hashId"),  # idProperty NO es unico en toctoc; hashId si
            url=r.get("urlFicha"),
            title=(r.get("titulo") or "").strip(),
            operation=r.get("tipoOperacion"),
            property_type=r.get("tipoPropiedad"),
            region=r.get("region"),
            commune=r.get("comuna"),
            price_uf=uf,
            price_clp=int(clp) if clp is not None else None,
            price_currency=self.CURRENCY_BY_TYPE.get(r.get("currencyType")),
            area_m2=area[0] if area else None,
            bedrooms=self._positive_ints(r.get("dormitorios")),
            bathrooms=self._positive_ints(r.get("bannos")),
            lat=r.get("latitud"),
            lon=r.get("longitud"),
            broker=(r.get("imagenInmobiliaria") or {}).get("alt"),
            hours_published=r.get("horasPublicado"),
            description=r.get("description"),
        )
        if item.area_m2 is None:
            from_text = self._area_from_text(item.title, item.description or "")
            if from_text is not None:
                item.area_m2 = from_text
                item.flags.append("area_from_text")  # dato inferido del texto, no del campo estructurado
            else:
                item.flags.append("area_missing")
        if item.price_clp is None and item.price_uf is None:
            item.flags.append("price_missing")
        if item.operation == "Arriendo" and item.price_clp and item.price_clp > self.MAX_ARRIENDO_CLP:
            item.flags.append("price_outlier")
        return item