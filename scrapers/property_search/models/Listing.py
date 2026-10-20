from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Listing:
    """Aviso normalizado: el mismo esquema para todos los sitios."""

    source: str  # nombre del sitio, ej. "toctoc"
    listing_id: str  # id unico DENTRO del sitio
    url: str
    title: str
    operation: Optional[str] = None
    property_type: Optional[str] = None
    region: Optional[str] = None
    commune: Optional[str] = None
    price_uf: Optional[float] = None
    price_clp: Optional[int] = None
    price_currency: Optional[str] = None  # moneda ORIGINAL del aviso: "UF" | "CLP" (el otro precio es derivado)
    area_m2: Optional[int] = None
    bedrooms: List[int] = field(default_factory=list)
    bathrooms: List[int] = field(default_factory=list)
    lat: Optional[float] = None
    lon: Optional[float] = None
    broker: Optional[str] = None
    hours_published: Optional[int] = None
    description: Optional[str] = None  # texto libre (estacionamiento, bodega, gastos comunes...)
    flags: List[str] = field(default_factory=list)  # avisos de calidad de datos

    def to_dict(self):
        return asdict(self)