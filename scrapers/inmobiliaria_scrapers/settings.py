"""Configuración de Scrapy para InmobiliarIA.

Las reglas de cortesía vienen de la revisión legal (2.1.3): respetar robots.txt,
pausar entre requests, identificarse con honestidad y no evadir bloqueos.
"""

import sys
from pathlib import Path

# Permite importar el paquete `core` de la raíz del repositorio
RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core.config import scraper_contacto  # noqa: E402

BOT_NAME = "inmobiliaria_scrapers"
SPIDER_MODULES = ["inmobiliaria_scrapers.spiders"]
NEWSPIDER_MODULE = "inmobiliaria_scrapers.spiders"

# --- Cortesía con los portales (no cambiar sin conversarlo con el equipo) ---
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2  # segundos entre requests al mismo portal
CONCURRENT_REQUESTS_PER_DOMAIN = 1
AUTOTHROTTLE_ENABLED = True  # se frena solo si el portal responde lento
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 30
USER_AGENT = (
    "InmobiliarIA-bot/0.1 (proyecto academico IIC3113; "
    f"contacto: {scraper_contacto()})"
)

# --- Robustez ---
RETRY_ENABLED = True
RETRY_TIMES = 3
DOWNLOAD_TIMEOUT = 30
HTTPCACHE_ENABLED = False  # ponlo en True mientras desarrollas selectores: no repite descargas

# --- Pipeline: valida, limpia y guarda cada aviso en la base ---
ITEM_PIPELINES = {
    "inmobiliaria_scrapers.pipelines.GuardarEnBasePipeline": 300,
}

LOG_LEVEL = "INFO"
FEED_EXPORT_ENCODING = "utf-8"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
