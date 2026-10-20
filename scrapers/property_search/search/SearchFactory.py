from __future__ import annotations

from typing import List

from .PropertySearch import PropertySearch
from search.sites.TocTocSearch import TocTocSearch


class SearchFactory:
    """Crea la busqueda del sitio pedido.

    Para agregar un sitio: crear su clase (NombreSearch.py, hereda de PropertySearch),
    importarla aqui y agregarla a _REGISTRY.
    """

    _REGISTRY = {
        TocTocSearch.name: TocTocSearch,
    }

    @classmethod
    def create(cls, site: str, **kwargs) -> PropertySearch:
        try:
            search_cls = cls._REGISTRY[site.strip().lower()]
        except KeyError:
            raise ValueError(f"Sitio '{site}' no soportado. Disponibles: {', '.join(cls.available())}")
        return search_cls(**kwargs)

    @classmethod
    def available(cls) -> List[str]:
        return sorted(cls._REGISTRY)
