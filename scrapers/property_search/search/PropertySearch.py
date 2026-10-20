from __future__ import annotations

import re
import time
import unicodedata
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

import httpx

try:
    from curl_cffi import requests as cffi
except ImportError:  # curl_cffi es opcional: sin el, se usa httpx
    cffi = None

from models.Listing import Listing
from models.SearchFilters import SearchFilters


class PropertySearch(ABC):
    """Clase de referencia: todas las busquedas por sitio heredan de aqui.

    La base hace lo comun (loop de paginacion, dedupe, pausa, fetch).
    Cada sitio implementa solo build_url() y extract().
    """

    name: str = ""  # id del sitio; lo usa el factory
    delay: float = 2.0  # segundos entre requests

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    }

    def __init__(self, delay: float | None = None):
        if delay is not None:
            self.delay = delay

    # --- lo que cada sitio debe implementar -------------------------------
    @abstractmethod
    def build_url(self, filters: SearchFilters, page: int = 1) -> str:
        """Traduce los filtros canonicos a la URL del sitio para esa pagina."""

    @abstractmethod
    def extract(self, html: str) -> List[Listing]:
        """Convierte el HTML de una pagina de resultados en avisos normalizados.
        Debe lanzar ValueError si el HTML no tiene el formato esperado."""

    # --- lo comun ----------------------------------------------------------
    def fetch(self, url: str) -> Tuple[int, str]:
        """Devuelve (status, html). Sobrescribible (ej. para usar Playwright)."""
        if cffi:
            r = cffi.get(url, headers=self.HEADERS, impersonate="chrome", timeout=30, allow_redirects=True)
            return r.status_code, r.text
        with httpx.Client(headers=self.HEADERS, follow_redirects=True, timeout=30) as c:
            r = c.get(url)
            return r.status_code, r.text

    def search(self, filters: SearchFilters, max_pages: int = 3) -> List[Listing]:
        """Recorre paginas hasta max_pages. Se detiene si la pagina falla,
        viene vacia o no trae ningun aviso nuevo (evita loops si el sitio repite la ultima pagina)."""
        seen: Dict[str, Listing] = {}
        for page in range(1, max_pages + 1):
            url = self.build_url(filters, page)
            status, html = self.fetch(url)
            if status != 200:
                if page == 1:
                    raise RuntimeError(f"{self.name}: HTTP {status} en {url}")
                break
            try:
                items = self.extract(html)
            except ValueError:
                if page == 1:
                    raise
                break
            new = [i for i in items if i.listing_id not in seen]
            if not new:
                break
            for item in new:
                seen[item.listing_id] = item
            if page < max_pages:
                time.sleep(self.delay)
        return list(seen.values())

    @staticmethod
    def slugify(text: str) -> str:
        """'Ñuñoa' -> 'nunoa', 'Estación Central' -> 'estacion-central'."""
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
