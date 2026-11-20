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


# --- IA (extracción de atributos y, más adelante, interpretación de búsquedas) ---
def ia_proveedores() -> list[str]:
    """Proveedores de IA en orden de preferencia, ej. 'gemini,groq'."""
    return [p.strip() for p in os.getenv("IA_PROVEEDORES", "gemini,groq").split(",") if p.strip()]


def ia_clave(proveedor: str) -> str | None:
    """Clave de API del proveedor (GEMINI_API_KEY, GROQ_API_KEY). None si no está."""
    return os.getenv(f"{proveedor.upper()}_API_KEY") or None


def ia_modelo(proveedor: str, por_defecto: str) -> str:
    return os.getenv(f"IA_MODELO_{proveedor.upper()}", por_defecto)


# --- Correo de aviso de nuevos leads (RF-07.04), con Resend ---
def resend_api_key() -> str | None:
    return os.getenv("RESEND_API_KEY") or None


def leads_correo_destino() -> str | None:
    """Casilla comercial de Aurora que recibe cada solicitud de contacto."""
    return os.getenv("LEADS_CORREO_DESTINO") or None


def leads_correo_remitente() -> str:
    # Sin dominio verificado en Resend solo se puede usar onboarding@resend.dev, y solo
    # hacia el correo con que se creó la cuenta de Resend.
    return os.getenv("LEADS_CORREO_REMITENTE", "InmobiliarIA <onboarding@resend.dev>")
