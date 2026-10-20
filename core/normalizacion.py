"""Funciones para llevar los datos de cada portal al formato común."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation


def slug(texto: str) -> str:
    """'Ñuñoa' -> 'nunoa', 'Las Condes' -> 'las-condes'. Igual al slug de la tabla comuna."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9\s-]", "", t)
    return re.sub(r"[\s-]+", "-", t).strip("-")


def _a_decimal(crudo: str) -> Decimal | None:
    """Interpreta un número escrito a la chilena.
    Con coma: el punto es de miles ('1.234,5' -> 1234.5).
    Sin coma: '1.200' o '550.000' son miles; '37.00' o '54.3' son decimales."""
    if "," in crudo:
        crudo = crudo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", crudo):
        crudo = crudo.replace(".", "")
    try:
        return Decimal(crudo)
    except InvalidOperation:
        return None


def numero(texto: str | None) -> Decimal | None:
    """Extrae el primer número de un texto: '$ 580.000' -> 580000, 'UF 14,13' -> 14.13,
    '55 m²' -> 55, '37.00 m²' -> 37.00. Devuelve None si no hay número."""
    if texto is None:
        return None
    m = re.search(r"\d[\d.]*(?:,\d+)?", str(texto))
    return _a_decimal(m.group(0).rstrip(".")) if m else None


def entero(texto: str | None) -> int | None:
    n = numero(texto)
    return int(n) if n is not None else None


# Primer precio escrito en un texto: "$ 550.000", "UF 13,35", "US$ 900", "USD 900"
_PRECIO = re.compile(r"(US\$|USD|UF|\$)\s*(\d[\d.]*(?:,\d+)?)", re.IGNORECASE)
_MONEDAS = {"$": "CLP", "UF": "UF", "US$": "USD", "USD": "USD"}


def precio(texto: str | None) -> tuple[Decimal | None, str | None]:
    """Devuelve (monto, moneda) del PRIMER precio del texto.
    '$ 550.000 Valor (UF aprox.) UF 13,35' -> (550000, 'CLP'): la UF de referencia no cuenta."""
    m = _PRECIO.search(texto or "")
    if not m:
        return None, None
    return _a_decimal(m.group(2).rstrip(".")), _MONEDAS[m.group(1).upper()]


def moneda_de(texto: str) -> str:
    """Moneda del primer precio del texto: 'UF 25' -> 'UF', 'US$ 900' -> 'USD', '$ 580' -> 'CLP'."""
    return precio(texto)[1] or "CLP"


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
