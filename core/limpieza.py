"""Quita datos personales de los textos de los avisos (regla de la revisión legal 2.1.3).

Se reemplazan por marcadores para que la IA sepa que ahí había un dato de contacto,
sin guardar el dato mismo: [correo], [telefono], [rut], [nombre].
"""

import re

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# RUT chileno: 12.345.678-9, 12345678-9, 9.876.543-K
_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")

# Teléfonos chilenos: +56 9 1234 5678, 912345678, 9 1234-5678, (2) 2345 6789, +56223456789.
# Exige un 9 (celular) o 2 (fijo Santiago) seguido de 8 dígitos, para no tocar precios
# como "580.000" o "$1.000.000".
_TELEFONO = re.compile(
    r"(?<![\d.$])(?:\+?\s?56[\s.-]?)?\(?[29]\)?[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)(?!\.\d)"
)

# Nombres tras un rótulo de contacto: "Agente: Carolina Contreras", "Contacto: Juan Pérez"
_NOMBRE_TRAS_ROTULO = re.compile(
    r"\b(Agente|Contacto|Corredora?|Ejecutiv[oa]|Atiende|Dueñ[oa])\s*:\s*"
    r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,3}"
)

_ESPACIOS = re.compile(r"[ \t]{2,}")


def limpiar_datos_personales(texto: str | None) -> str | None:
    """Devuelve el texto sin correos, RUT, teléfonos ni nombres tras un rótulo de contacto."""
    if texto is None:
        return None
    t = _CORREO.sub("[correo]", texto)
    t = _RUT.sub("[rut]", t)
    t = _TELEFONO.sub("[telefono]", t)
    t = _NOMBRE_TRAS_ROTULO.sub(lambda m: f"{m.group(1)}: [nombre]", t)
    return _ESPACIOS.sub(" ", t).strip()


def contiene_datos_personales(texto: str | None) -> bool:
    """True si el texto todavía tiene un correo, RUT o teléfono reconocible."""
    if not texto:
        return False
    return bool(_CORREO.search(texto) or _RUT.search(texto) or _TELEFONO.search(texto))
