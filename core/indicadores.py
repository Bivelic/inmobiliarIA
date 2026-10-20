"""Valor de la UF del día, para convertir precios entre UF y pesos."""

import json
import os
import urllib.request
from decimal import Decimal

MINDICADOR_UF = "https://mindicador.cl/api/uf"


def obtener_valor_uf() -> Decimal | None:
    """Devuelve el valor de la UF de hoy.

    Orden: variable de entorno VALOR_UF (útil para pruebas o si la API falla),
    luego la API pública de mindicador.cl. Devuelve None si no lo consigue;
    en ese caso los precios en UF quedan sin convertir, pero el aviso se guarda igual.
    """
    if os.getenv("VALOR_UF"):
        return Decimal(os.environ["VALOR_UF"])
    try:
        with urllib.request.urlopen(MINDICADOR_UF, timeout=10) as r:
            datos = json.load(r)
        return Decimal(str(datos["serie"][0]["valor"]))
    except Exception:  # noqa: BLE001 - cualquier falla deja la UF sin valor
        return None
