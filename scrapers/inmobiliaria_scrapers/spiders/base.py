"""Clase base para los spiders de cada portal.

Cada portal hereda de `AvisoSpider` y solo implementa cómo leer SU listado y SU ficha.
El resto (validación, limpieza, guardado y conteos) lo hace el pipeline.

Argumentos de línea de comandos comunes:
    scrapy crawl <portal> -a max_paginas=5    # corrida corta, para probar
    scrapy crawl <portal>                      # corrida completa (marca bajas al final)
"""

import scrapy


class AvisoSpider(scrapy.Spider):
    # Cada spider define: name (igual al código en la tabla portal) y allowed_domains

    def __init__(self, max_paginas=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_paginas = int(max_paginas) if max_paginas else None
        # Solo una corrida sin límite permite marcar como inactivos los avisos no vistos
        self.corrida_completa = self.max_paginas is None
        self.paginas_visitadas = 0
        self.errores: list[tuple[str, str, str]] = []  # (url, tipo, mensaje) -> error_scraping

    def puede_seguir(self, pagina_siguiente: int) -> bool:
        """pagina_siguiente cuenta desde 0. Respeta max_paginas si se indicó."""
        return self.max_paginas is None or pagina_siguiente < self.max_paginas

    def error_descarga(self, failure):
        """Usar como errback=self.error_descarga en cada Request de ficha."""
        url = failure.request.url
        self.errores.append((url, "http", repr(failure.value)[:500]))
        self.logger.warning(f"Falló la descarga de {url}: {failure.value!r}")

    def error_lectura(self, response, excepcion: Exception):
        """Llamar dentro de un except al leer una ficha cuyo HTML no se pudo interpretar."""
        self.errores.append((response.url, "parseo", f"{type(excepcion).__name__}: {excepcion}"))
        self.logger.warning(f"No se pudo leer {response.url}: {excepcion}")
