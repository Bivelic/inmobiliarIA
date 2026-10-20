"""Lee la configuración desde variables de entorno (archivo .env en la raíz)."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _obligatoria(nombre: str) -> str:
    valor = os.getenv(nombre)
    if not valor:
        raise RuntimeError(
            f"Falta la variable {nombre}. Copia .env.example como .env y complétala."
        )
    return valor


def database_url() -> str:
    return _obligatoria("DATABASE_URL")


def cors_origins() -> list[str]:
    return [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]


def scraper_contacto() -> str:
    return os.getenv("SCRAPER_CONTACTO", "sin-contacto")
