from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import quote

from models.Listing import Listing
from search.PropertySearch import PropertySearch
from models.SearchFilters import Range, SearchFilters

PUSH_RE = re.compile(r"<script[^>]*>self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
TEXT_ROW_RE = re.compile(rb"([0-9a-f]+):T([0-9a-f]+),")  # fila de texto largo: <id>:T<largo en hex>,<texto>
DATA_MARK = '"initialResults":{"data":'


class YapoSearch(PropertySearch):
    """yapo.cl: sitio Next.js (App Router). No hay __NEXT_DATA__: los avisos viajan en los fragmentos
    self.__next_f.push([1,"..."]), dentro de "initialResults":{"data":[...]} (20 avisos por pagina).
    Las descripciones largas vienen como referencia ("$21") a una fila de texto aparte; se resuelven aqui.

    URL:    /bienes-raices-{alquiler|venta}-{apartamentos|casas}[.{pagina}]/region-{region}-{comuna}[?q=filtros]
    Filtros dentro de q, separados por '|':  f_price.A-B | f_rooms.A-B | f_bath.A-B | time.DIAS
            (un '-' al final, ej. f_rooms.2-, significa 'o mas').
    Verificado solo para arriendo de departamentos en la Region Metropolitana; 'venta', 'casas', otras regiones
    y el limite inferior abierto (0) estan SIN VERIFICAR. Yapo no resuelve barrios: neighborhood se ignora.
    No se lee ni se guarda nada del anunciante (nombre, telefono, whatsapp): son datos personales.
    """

    name = "yapo"
    BASE = "https://www.yapo.cl"
    PAGE_SIZE = 20
    MAX_ARRIENDO_CLP = 10_000_000
    OPERATION_SLUG = {"arriendo": "alquiler", "venta": "venta"}
    TYPE_SLUG = {"departamento": "apartamentos", "casa": "casas"}
    OPERATION_LABEL = {"rent": "Arriendo", "sale": "Venta"}
    TYPE_LABEL = {"Apartamento": "Departamento", "Casa": "Casa"}

    # ------------------------------------------------------------------ URL
    @staticmethod
    def _range(rng: Range) -> str:
        lo, hi = rng
        return f"{0 if lo is None else lo}-{'' if hi is None else hi}"

    def build_url(self, filters: SearchFilters, page: int = 1) -> str:
        operation = self.OPERATION_SLUG.get(filters.operation)
        prop_type = self.TYPE_SLUG.get(self.slugify(filters.property_type))
        if not operation:
            raise ValueError("yapo: operation debe ser 'arriendo' o 'venta'")
        if not prop_type:
            raise ValueError("yapo: property_type soportado: departamento, casa")
        if filters.area_util:
            raise ValueError("yapo: no hay filtro de superficie")
        if filters.price and filters.currency != "CLP":
            raise ValueError("yapo: el filtro de precio solo se admite en CLP (unidad de UF sin verificar)")

        parts = []
        if filters.price:
            parts.append(f"f_price.{self._range(filters.price)}")
        if filters.bedrooms:
            parts.append(f"f_rooms.{self._range(filters.bedrooms)}")
        if filters.bathrooms:
            parts.append(f"f_bath.{self._range(filters.bathrooms)}")
        if filters.published_within_days is not None:
            parts.append(f"time.{filters.published_within_days}")

        category = f"bienes-raices-{operation}-{prop_type}" + (f".{page}" if page > 1 else "")
        url = f"{self.BASE}/{category}/region-{self.slugify(filters.region)}-{self.slugify(filters.commune)}"
        if parts:
            url += "?q=" + quote("|".join(parts), safe="._-")  # '|' va como %7C
        return url

    # ------------------------------------------------------------- extraccion
    @staticmethod
    def _flight(html: str) -> str:
        chunks = []
        for match in PUSH_RE.finditer(html):
            try:
                payload = json.loads(match.group(1))
            except ValueError:
                continue
            if len(payload) > 1 and isinstance(payload[1], str):
                chunks.append(payload[1])
        return "".join(chunks)

    @staticmethod
    def _text_rows(flight: str) -> Dict[str, str]:
        """Filas '<id>:T<largo>,<texto>' (el largo es en bytes). Pueden venir encadenadas, sin salto de linea."""
        data = flight.encode("utf-8")
        rows: Dict[str, str] = {}
        pos = 0
        first = re.compile(rb"(?:^|\n)([0-9a-f]+):T([0-9a-f]+),")
        while True:
            found = first.search(data, pos)
            if not found:
                break
            cursor = found.start() + (1 if data[found.start()] == 10 else 0)
            while True:
                row = TEXT_ROW_RE.match(data, cursor)
                if not row:
                    break
                size = int(row.group(2), 16)
                rows[row.group(1).decode()] = data[row.end():row.end() + size].decode("utf-8", errors="replace")
                cursor = row.end() + size
                if data[cursor:cursor + 1] == b"\n":
                    cursor += 1
            pos = max(cursor, found.end())
        return rows

    def extract(self, html: str) -> List[Listing]:
        flight = self._flight(html)
        index = flight.find(DATA_MARK)
        if index < 0:
            raise ValueError("yapo: no hay initialResults en el HTML (pagina bloqueada o cambio de formato)")
        try:
            ads, _ = json.JSONDecoder().raw_decode(flight[index + len(DATA_MARK):])
        except ValueError as error:
            raise ValueError(f"yapo: estructura inesperada ({error!r})")
        texts = self._text_rows(flight)
        return [self._to_listing(ad, texts) for ad in ads if isinstance(ad, dict)]

    @staticmethod
    def _date(value) -> Optional[datetime]:
        """Las fechas vienen como '$D2026-11-05T14:59:59.000Z'."""
        if not isinstance(value, str) or not value.startswith("$D"):
            return None
        try:
            return datetime.fromisoformat(value[2:].replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _int_or_none(value) -> Optional[int]:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _to_listing(self, ad: dict, texts: Dict[str, str]) -> Listing:
        # precio: bloque 'rent' (o 'sale'); si falta, price_value. La moneda manda lo que el sitio MUESTRA
        # (price_symbol: "UF" o "$$"), porque currency.symbol a veces dice USD en avisos que se ven en pesos.
        block = ad.get(ad.get("fieldset") or "rent") or {}
        amount = (block.get("amount") or {}).get("value") or ad.get("price_value")
        symbol = (block.get("currency") or {}).get("symbol")
        display = ad.get("price_symbol")
        uf = clp = None
        currency = None
        flags: List[str] = []
        if amount and (symbol == "CLF" or display == "UF"):
            uf, currency = float(amount), "UF"
        elif amount and (symbol == "CLP" or display == "$$"):
            clp, currency = int(amount), "CLP"
            if symbol not in (None, "CLP"):
                flags.append(f"currency_{symbol.lower()}_shown_as_clp")  # trazabilidad: se confio en lo que muestra el sitio
        elif amount:
            flags.append(f"currency_{(symbol or 'unknown').lower()}")  # moneda no soportada: no se adivina ni se convierte

        description = ad.get("description")
        if isinstance(description, str) and description.startswith("$"):
            description = texts.get(description[1:])  # None si no se pudo resolver ('$undefined' tampoco existe)

        location = ad.get("location") or {}
        locality = location.get("locality") or ""
        created = self._date(ad.get("dateCreated"))
        hours = int((datetime.now(timezone.utc) - created).total_seconds() // 3600) if created else None

        item = Listing(
            source=self.name,
            listing_id=str(ad.get("id")),
            url=f"{self.BASE}{ad['link']}" if ad.get("link") else None,
            title=(ad.get("title") or "").strip(),
            operation=self.OPERATION_LABEL.get(ad.get("fieldset")),
            property_type=self.TYPE_LABEL.get(ad.get("subCategoryType"), ad.get("subCategoryType")),
            region=locality.split(",")[0].strip() or None,
            commune=ad.get("regionName") or (locality.split(",")[-1].strip() or None),
            address=location.get("address") or None,
            price_uf=uf,
            price_clp=clp,
            price_currency=currency,
            area_m2=self._int_or_none(ad.get("square")),
            bedrooms=[n] if (n := self._int_or_none(ad.get("rooms"))) else [],
            bathrooms=[n] if (n := self._int_or_none(ad.get("bathrooms"))) else [],
            lat=location.get("lat") or None,  # 0 = sin dato
            lon=location.get("lon") or None,
            broker=None,  # el anunciante es dato personal: no se guarda
            hours_published=hours,
            description=description if isinstance(description, str) else None,
            flags=flags,
        )
        if item.area_m2 is None:
            item.flags.append("area_missing")
        if uf is None and clp is None:
            item.flags.append("price_missing")
        if item.operation == "Arriendo" and clp and clp > self.MAX_ARRIENDO_CLP:
            item.flags.append("price_outlier")
        return item