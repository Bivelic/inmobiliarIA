"""Formato común del aviso: el contrato entre los scrapers, la base de datos y la API.

Cada spider produce un diccionario con estos campos; el pipeline lo valida con
`AvisoNormalizado` y lo guarda en la tabla `publicacion`. Si un campo cambia aquí,
hay que cambiarlo también en db/01_schema.sql.
"""

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from core.limpieza import limpiar_datos_personales

Portal = Literal["chilepropiedades", "yapo", "economicos", "toctoc"]
Operacion = Literal["arriendo", "venta"]
TipoPropiedad = Literal["departamento", "casa", "estudio", "otro"]
Moneda = Literal["CLP", "UF", "USD"]


class AvisoNormalizado(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    # Identidad del aviso
    portal: Portal
    id_externo: str = Field(min_length=1)
    url: HttpUrl
    operacion: Operacion
    tipo_propiedad: TipoPropiedad

    # Texto (se limpia de datos personales al validar)
    titulo: str = Field(min_length=3)
    descripcion: str | None = None

    # Precio tal como venía + valores normalizados (los calcula el pipeline)
    precio_monto: Decimal = Field(gt=0)
    precio_moneda: Moneda
    precio_clp: Decimal | None = Field(default=None, gt=0)
    precio_uf: Decimal | None = Field(default=None, gt=0)
    gastos_comunes_clp: Decimal | None = Field(default=None, ge=0)

    # Ubicación: comuna en texto libre; el pipeline la resuelve contra la tabla comuna
    comuna: str | None = None
    sector: str | None = None
    latitud: Decimal | None = Field(default=None, ge=-90, le=90)
    longitud: Decimal | None = Field(default=None, ge=-180, le=180)

    # Campos estructurados del portal
    dormitorios: int | None = Field(default=None, ge=0, le=20)
    banos: int | None = Field(default=None, ge=0, le=20)
    m2_util: Decimal | None = Field(default=None, gt=0)
    m2_total: Decimal | None = Field(default=None, gt=0)
    estacionamientos: int | None = Field(default=None, ge=0)
    fecha_publicacion: date | None = None

    @field_validator("titulo", "descripcion", mode="after")
    @classmethod
    def _sin_datos_personales(cls, v: str | None) -> str | None:
        return limpiar_datos_personales(v)

    @model_validator(mode="after")
    def _precio_plausible(self):
        """Rechaza precios imposibles: casi siempre son un error de lectura (ej. leer
        '$ 550.000' como 550.000 UF). El aviso queda en error_scraping para revisarlo."""
        limites = {  # (mínimo, máximo) por operación y moneda
            ("arriendo", "CLP"): (50_000, 20_000_000),
            ("arriendo", "UF"): (1, 500),
            ("venta", "CLP"): (5_000_000, 50_000_000_000),
            ("venta", "UF"): (200, 1_000_000),
        }
        rango = limites.get((self.operacion, self.precio_moneda))
        if rango and not rango[0] <= self.precio_monto <= rango[1]:
            raise ValueError(
                f"precio fuera de rango para {self.operacion} en {self.precio_moneda}: "
                f"{self.precio_monto} (esperado entre {rango[0]} y {rango[1]})"
            )
        return self

    @model_validator(mode="after")
    def _m2_coherentes(self):
        if self.m2_util and self.m2_total and self.m2_util > self.m2_total * Decimal("1.5"):
            # Probable error del publicante: se conserva el total y se descarta el útil
            self.m2_util = None
        return self

    def hash_contenido(self) -> str:
        """Huella de los campos que importan: si cambia, el aviso se actualiza en la base."""
        datos = self.model_dump(mode="json", exclude={"url"})
        crudo = json.dumps(datos, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()
