from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# Rango (minimo, maximo). None = sin limite en ese extremo.
Range = Tuple[Optional[int], Optional[int]]


@dataclass
class SearchFilters:
    """Filtros canonicos de busqueda: iguales para todos los sitios.
    Cada clase de busqueda (TocTocSearch, etc.) los traduce al formato de su sitio."""

    operation: str  # "venta" | "arriendo"
    property_type: str  # "departamento" | "casa" | ...
    region: str = "metropolitana"
    commune: Optional[str] = None
    neighborhood: Optional[str] = None
    bedrooms: Optional[Range] = None
    bathrooms: Optional[Range] = None
    price: Optional[Range] = None
    currency: Optional[str] = None  # "UF" | "CLP" (obligatoria si hay price)
    area_util: Optional[Range] = None  # m2 utiles
    published_within_days: Optional[int] = None

    def __post_init__(self):
        self.operation = self.operation.strip().lower()
        if self.currency:
            self.currency = self.currency.strip().upper()
            if self.currency not in ("UF", "CLP"):
                raise ValueError("currency debe ser 'UF' o 'CLP'")
        if self.price and not self.currency:
            raise ValueError("Si defines price tambien debes definir currency (UF o CLP)")
        if self.neighborhood and not self.commune:
            raise ValueError("neighborhood requiere commune")
        for name in ("bedrooms", "bathrooms", "price", "area_util"):
            rng = getattr(self, name)
            if rng and rng[0] is not None and rng[1] is not None and rng[0] > rng[1]:
                raise ValueError(f"{name}: el minimo ({rng[0]}) es mayor que el maximo ({rng[1]})")
        if self.published_within_days is not None and self.published_within_days < 1:
            raise ValueError("published_within_days debe ser >= 1")
