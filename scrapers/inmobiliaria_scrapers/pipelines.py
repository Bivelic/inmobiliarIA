"""Pipeline de Scrapy: pasa cada aviso al guardado común (core/guardado.py)."""

from scrapy.exceptions import DropItem

from core.guardado import Ejecucion


class GuardarEnBasePipeline:
    def open_spider(self, spider):
        self.ejecucion = Ejecucion(spider.name)
        spider.logger.info(f"Ejecución {self.ejecucion.id} iniciada")

    def process_item(self, item, spider):
        if not self.ejecucion.procesar(dict(item)):
            raise DropItem(f"Aviso con error: {item.get('url')}")
        return item

    def close_spider(self, spider, reason=None):
        # Errores de descarga o de lectura que el spider anotó (no llegaron como avisos)
        for url, tipo, mensaje in getattr(spider, "errores", []):
            self.ejecucion.error_sin_aviso(url, tipo, mensaje)
        resumen = self.ejecucion.cerrar(
            terminada=reason in (None, "finished"),
            completa=getattr(spider, "corrida_completa", False),
            paginas=getattr(spider, "paginas_visitadas", 0),
        )
        spider.logger.info(resumen)
