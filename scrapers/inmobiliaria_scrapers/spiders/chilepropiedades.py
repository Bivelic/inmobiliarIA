"""Spider de Chilepropiedades: departamentos en arriendo en la Región Metropolitana.

Listado:  https://chilepropiedades.cl/propiedades/arriendo-mensual/departamento/region-metropolitana-de-santiago-rm/0
          (10 avisos por página; la página va al final de la URL: /0, /1, /2 ...)
Ficha:    https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/<comuna>/departamento/<slug>/<codigo>

IMPORTANTE: los selectores de la ficha se escribieron a partir del texto de la página, sin
poder probarlos contra el HTML real. Antes de la primera corrida, verifícalos con:
    scrapy shell "https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/nunoa/departamento/vicuna-mackenna-660/137904440"
y ajusta `_valor()` o los XPath si algún campo sale vacío.

Nunca se lee el bloque "Información de Contacto" ni el enlace de WhatsApp (regla 2.1.3).
"""

import re
from datetime import datetime

import scrapy

from core.normalizacion import entero, moneda_de, numero
from inmobiliaria_scrapers.spiders.base import AvisoSpider

LISTADO = (
    "https://chilepropiedades.cl/propiedades/arriendo-mensual/departamento/"
    "region-metropolitana-de-santiago-rm/{pagina}"
)
# /ver-publicacion/<operacion>/<comuna>/<tipo>/<slug>/<codigo>
TIPOS = ("departamento", "casa", "estudio")
RUTA_FICHA = re.compile(r"/ver-publicacion/([^/]+)/([^/]+)/([^/]+)/[^/]+/(\d+)")


class ChilepropiedadesSpider(AvisoSpider):
    name = "chilepropiedades"
    allowed_domains = ["chilepropiedades.cl"]

    async def start(self):
        yield self._pedir_listado(0)

    def _pedir_listado(self, pagina: int) -> scrapy.Request:
        return scrapy.Request(
            LISTADO.format(pagina=pagina), callback=self.parse, cb_kwargs={"pagina": pagina}
        )

    # ---------------------------------------------------------------- listado
    def parse(self, response, pagina: int):
        self.paginas_visitadas += 1
        fichas = []
        for href in response.css('a[href*="/ver-publicacion/"]::attr(href)').getall():
            url = response.urljoin(href)
            if url not in fichas:
                fichas.append(url)

        self.logger.info(f"Página {pagina}: {len(fichas)} avisos")
        for url in fichas:
            yield response.follow(url, callback=self.parse_aviso, errback=self.error_descarga)

        # Sigue con la página siguiente mientras haya avisos y no se pase de max_paginas
        if fichas and self.puede_seguir(pagina + 1):
            yield self._pedir_listado(pagina + 1)

    # ---------------------------------------------------------------- ficha
    def parse_aviso(self, response):
        try:
            yield self._leer_ficha(response)
        except Exception as e:  # noqa: BLE001 - cualquier falla se registra y se sigue
            self.error_lectura(response, e)

    def _leer_ficha(self, response) -> dict:
        ruta = RUTA_FICHA.search(response.url)
        if not ruta:
            raise ValueError("URL de ficha con formato inesperado")
        operacion_url, comuna_slug, tipo_url, codigo = ruta.groups()

        precio_texto = self._valor(response, "Valor") or ""
        return {
            "portal": self.name,
            "id_externo": self._valor(response, "Código Aviso") or codigo,
            "url": response.url,
            "operacion": "venta" if operacion_url.startswith("venta") else "arriendo",
            "tipo_propiedad": tipo_url if tipo_url in TIPOS else "otro",
            "titulo": self._texto(response.xpath("//h1")),
            "descripcion": self._descripcion(response),
            "precio_monto": numero(precio_texto),
            "precio_moneda": moneda_de(precio_texto),
            "gastos_comunes_clp": numero(self._valor(response, "Gastos Comunes")),
            "comuna": comuna_slug,  # el pipeline la resuelve contra la tabla comuna por slug
            "dormitorios": entero(self._valor(response, "Habitaciones")),
            "banos": entero(self._valor(response, "Baños")),
            "estacionamientos": entero(self._valor(response, "Estac.")),
            "m2_util": numero(self._valor(response, "Superficie Útil")),
            "m2_total": numero(
                self._valor(response, "Superficie Total") or self._valor(response, "Superficie")
            ),
            "fecha_publicacion": self._fecha(self._valor(response, "Fecha Publicación")),
        }

    # ---------------------------------------------------------------- ayudas
    @staticmethod
    def _texto(selector) -> str:
        return " ".join(" ".join(selector.xpath(".//text()").getall()).split())

    def _valor(self, response, etiqueta: str) -> str | None:
        """Busca un rótulo (ej. 'Gastos Comunes') y devuelve el texto que lo acompaña
        en el mismo bloque (ej. '$ 96.000'). Toma la primera aparición."""
        for nodo in response.xpath("//*[normalize-space(text()) = $e]", e=etiqueta):
            bloque = self._texto(nodo.xpath(".."))
            resto = bloque.replace(etiqueta, "", 1).strip(" :")
            if resto:
                return resto
        return None

    def _descripcion(self, response) -> str | None:
        nodo = response.xpath("//h2[normalize-space() = 'Descripción']/following-sibling::*[1]")
        texto = self._texto(nodo) if nodo else ""
        texto = texto.replace("Ver descripción completa", "").replace("Ver menos", "").strip()
        return texto or None

    @staticmethod
    def _fecha(texto: str | None):
        if not texto:
            return None
        m = re.search(r"\d{2}/\d{2}/\d{4}", texto)
        return datetime.strptime(m.group(0), "%d/%m/%Y").date() if m else None
