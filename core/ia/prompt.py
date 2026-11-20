"""Instrucciones para el modelo (EDT 3.2.1) y armado de cada lote de avisos.

La versión del prompt queda guardada en cada extracción (tabla extraccion_ia). Incluye un
resumen (hash) del catálogo: si se cambia una regla o la lista de atributos, cambia la versión
y los avisos se vuelven a procesar solos en la próxima corrida.
"""

import hashlib
import json
from dataclasses import dataclass

from core.ia.catalogo import Atributo

# Subir este número al cambiar las REGLAS de abajo (el catálogo ya se versiona solo).
VERSION_REGLAS = "v1"

# Tope de texto por aviso, para acotar tokens (y costo) en descripciones muy largas.
MAX_CARACTERES = 3000

REGLAS = """\
Eres un extractor de datos de avisos de arriendo y venta de propiedades en Chile.
Recibes varios avisos (id, título y descripción) y un catálogo de atributos.
Para cada aviso, informa SOLO los atributos que el título o la descripción mencionan
de forma explícita.

Reglas:
1. Si el aviso no menciona un atributo, NO lo incluyas. No lo deduzcas ni lo supongas
   (por ejemplo, un edificio nuevo no implica gimnasio; una comuna no implica cercanía al metro).
2. Un atributo booleano es false solo si el aviso lo niega de forma explícita
   (por ejemplo, "no se aceptan mascotas" o "sin estacionamiento").
3. "evidencia" es una copia LITERAL y breve (máximo 120 caracteres) del fragmento del título
   o de la descripción que respalda el valor. No la resumas ni la corrijas.
4. "confianza" es un número entre 0 y 1 que indica qué tan claro es el texto.
5. Usa el tipo indicado en el catálogo: booleano = true/false; numero = número sin puntos ni
   símbolos; texto = texto corto.
6. Responde únicamente con un objeto JSON con esta forma, incluyendo TODOS los avisos recibidos
   (con "atributos": {} si no tienen ninguno):
   {"avisos": [{"id": 123, "atributos":
       {"<codigo>": {"valor": true, "evidencia": "...", "confianza": 0.9}}}]}
"""


@dataclass(frozen=True)
class AvisoParaIA:
    id: int
    titulo: str
    descripcion: str


def texto_catalogo(catalogo: list[Atributo]) -> str:
    return "\n".join(f"- {a.codigo} ({a.tipo_dato}): {a.descripcion}" for a in catalogo)


def instrucciones(catalogo: list[Atributo]) -> str:
    """Mensaje de sistema: reglas + catálogo."""
    return f"{REGLAS}\nCatálogo de atributos:\n{texto_catalogo(catalogo)}\n"


def version_prompt(catalogo: list[Atributo]) -> str:
    huella = hashlib.sha256(instrucciones(catalogo).encode("utf-8")).hexdigest()[:8]
    return f"{VERSION_REGLAS}-{huella}"


def mensaje_lote(avisos: list[AvisoParaIA]) -> str:
    """Mensaje de usuario: los avisos del lote en JSON (así su texto no se confunde
    con instrucciones)."""
    datos = [
        {"id": a.id, "titulo": a.titulo, "descripcion": (a.descripcion or "")[:MAX_CARACTERES]}
        for a in avisos
    ]
    return "Avisos (JSON):\n" + json.dumps(datos, ensure_ascii=False)
