"""Funciones para llevar los datos de cada portal al formato común."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation


def slug(texto: str) -> str:
    """'Ñuñoa' -> 'nunoa', 'Las Condes' -> 'las-condes'. Igual al slug de la tabla comuna."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9\s-]", "", t)
    return re.sub(r"[\s-]+", "-", t).strip("-")


def numero(texto: str | None) -> Decimal | None:
    """Extrae un número de textos chilenos: '$ 580.000' -> 580000, 'UF 14,13' -> 14.13,
    '55 m²' -> 55. Devuelve None si no hay número."""
    if texto is None:
        return None
    m = re.search(r"\d[\d.]*(?:,\d+)?", str(texto))
    if not m:
        return None
    crudo = m.group(0).replace(".", "").replace(",", ".")
    try:
        return Decimal(crudo)
    except InvalidOperation:
        return None


def entero(texto: str | None) -> int | None:
    n = numero(texto)
    return int(n) if n is not None else None


def moneda_de(texto: str) -> str:
    """Detecta la moneda de un precio escrito.
    'UF 25' -> 'UF', 'US$ 900' -> 'USD', '$ 580.000' -> 'CLP'."""
    t = texto.upper()
    if "UF" in t:
        return "UF"
    if "US" in t or "USD" in t:
        return "USD"
    return "CLP"


def a_clp(
    monto: Decimal, moneda: str, valor_uf: Decimal | None, valor_usd: Decimal | None = None
) -> Decimal | None:
    """Convierte un precio a pesos. Devuelve None si falta el valor de conversión."""
    if moneda == "CLP":
        return monto
    if moneda == "UF" and valor_uf:
        return (monto * valor_uf).quantize(Decimal("1"))
    if moneda == "USD" and valor_usd:
        return (monto * valor_usd).quantize(Decimal("1"))
    return None


def a_uf(monto_clp: Decimal | None, valor_uf: Decimal | None) -> Decimal | None:
    if monto_clp is None or not valor_uf:
        return None
    return (monto_clp / valor_uf).quantize(Decimal("0.01"))
