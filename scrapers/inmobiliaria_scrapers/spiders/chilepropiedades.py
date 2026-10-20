"""Spider de Chilepropiedades: departamentos en arriendo en la Región Metropolitana.

Listado:  https://chilepropiedades.cl/propiedades/arriendo-mensual/departamento/region-metropolitana-de-santiago-rm/0
          (10 avisos por página; la página va al final de la URL: /0, /1, /2 ...)
Ficha:    https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/<comuna>/departamento/<slug>/<codigo>

Cómo se lee la ficha (verificado contra una ficha real el 20/10/2026, ver tests/fixtures):
  1. Datos estructurados JSON-LD (RealEstateListing): precio, moneda, dormitorios, baños,
     estacionamientos, superficies, gastos comunes y fecha. Es lo más confiable.
  2. Rótulos del HTML ("Habitaciones", "Valor"...): solo como respaldo si falta el JSON-LD.
  3. Descripción completa desde .clp-description-box (la del JSON-LD viene recortada).
  4. Coordenadas desde `var publicationLocation = [lat, lon]` del mapa.

Nunca se lee el bloque "Información de Contacto" ni el enlace de WhatsApp (regla 2.1.3).
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import scrapy

from core.normalizacion import entero, numero, precio
from inmobiliaria_scrapers.spiders.base import AvisoSpider

LISTADO = (
    "https://chilepropiedades.cl/propiedades/arriendo-mensual/departamento/"
    "region-metropolitana-de-santiago-rm/{pagina}"
)
# /ver-publicacion/<operacion>/<comuna>/<tipo>/<slug>/<codigo>
TIPOS = ("departamento", "casa", "estudio")
RUTA_FICHA = re.compile(r"/ver-publicacion/([^/]+)/([^/]+)/([^/]+)/[^/]+/(\d+)")


def _decimal_json(valor) -> Decimal | None:
    """Números del JSON-LD: vienen con punto decimal ('550000', '25.5'), no a la chilena."""
    try:
        return Decimal(str(valor)) if valor not in (None, "") else None
    except InvalidOperation:
        return None


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

        # 1) Datos estructurados (JSON-LD de schema.org): la fuente más confiable
        ld = self._datos_estructurados(response)
        # 2) Rótulos del HTML: respaldo si la página no trae JSON-LD o le falta algún campo
        monto, moneda = precio(self._valor(response, "Valor"))
        html = {
            "titulo": self._texto(response.xpath("//h1")),
            "precio_monto": monto,
            "precio_moneda": moneda,
            "gastos_comunes_clp": numero(self._valor(response, "Gastos Comunes")),
            "dormitorios": entero(self._valor(response, "Habitaciones")),
            "banos": entero(self._valor(response, "Baños")),
            "estacionamientos": entero(self._valor(response, "Estac.")),
            "m2_util": numero(self._valor(response, "Superficie Útil")),
            "m2_total": numero(
                self._valor(response, "Superficie Total") or self._valor(response, "Superficie")
            ),
            "fecha_publicacion": self._fecha(self._valor(response, "Fecha Publicación")),
        }
        datos = {k: ld.get(k) if ld.get(k) is not None else v for k, v in html.items()}
        lat, lon = self._coordenadas(response)

        return {
            "portal": self.name,
            "id_externo": codigo,
            "url": response.url,
            "operacion": "venta" if operacion_url.startswith("venta") else "arriendo",
            "tipo_propiedad": tipo_url if tipo_url in TIPOS else "otro",
            # La descripción del JSON-LD viene recortada ("..."): se prefiere la del HTML
            "descripcion": self._descripcion(response) or ld.get("descripcion"),
            "comuna": comuna_slug,  # el pipeline la resuelve contra la tabla comuna por slug
            "latitud": lat,
            "longitud": lon,
            **datos,
        }

    # ---------------------------------------------------------------- datos estructurados
    _MONEDA_LD = {"CLP": "CLP", "CLF": "UF", "UF": "UF", "USD": "USD"}  # CLF = código ISO de la UF

    def _datos_estructurados(self, response) -> dict:
        """Lee el bloque <script type="application/ld+json"> (RealEstateListing)."""
        for bloque in response.xpath('//script[@type="application/ld+json"]/text()').getall():
            try:
                contenido = json.loads(bloque)
            except json.JSONDecodeError:
                continue
            nodos = contenido.get("@graph", [contenido]) if isinstance(contenido, dict) else []
            aviso = next((n for n in nodos if n.get("@type") == "RealEstateListing"), None)
            if not aviso:
                continue
            props = {
                str(p.get("name", "")).strip().lower(): p.get("value")
                for p in (aviso.get("about") or {}).get("additionalProperty", [])
            }
            oferta = aviso.get("offers") or {}
            fecha = aviso.get("datePosted")
            return {
                "titulo": aviso.get("name"),
                "descripcion": aviso.get("description"),
                "precio_monto": _decimal_json(oferta.get("price")),
                "precio_moneda": self._MONEDA_LD.get(str(oferta.get("priceCurrency", "")).upper()),
                "gastos_comunes_clp": numero(props.get("gastos comunes")),
                "dormitorios": entero(props.get("dormitorios")),
                "banos": entero(props.get("baños")),
                "estacionamientos": entero(props.get("estacionamientos")),
                "m2_util": numero(props.get("superficie útil")),
                "m2_total": numero(props.get("superficie total")),
                "fecha_publicacion": date.fromisoformat(fecha[:10]) if fecha else None,
            }
        return {}

    @staticmethod
    def _coordenadas(response):
        """El mapa de la ficha define `var publicationLocation = [ lat, lon ]`."""
        m = re.search(
            r"publicationLocation\s*=\s*\[\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*\]", response.text
        )
        return (Decimal(m.group(1)), Decimal(m.group(2))) if m else (None, None)

    # ---------------------------------------------------------------- ayudas
    @staticmethod
    def _texto(selector) -> str:
        return " ".join(" ".join(selector.xpath(".//text()").getall()).split())

    # Los buscadores de la página (arriba y al costado) también tienen rótulos como
    # "Habitaciones" con opciones "0+ 1+ 2+": se ignoran para no leer un 0 falso.
    _FUERA_DEL_AVISO = "ancestor::form or ancestor::header or ancestor::nav or ancestor::footer"

    def _valor(self, response, etiqueta: str) -> str | None:
        """Busca un rótulo (ej. 'Gastos Comunes') y devuelve el texto que lo acompaña
        en el mismo bloque (ej. '$ 96.000'). Toma la primera aparición dentro del aviso."""
        nodos = response.xpath(
            f"//*[normalize-space(text()) = $e][not({self._FUERA_DEL_AVISO})]", e=etiqueta
        )
        for nodo in nodos:
            bloque = self._texto(nodo.xpath(".."))
            resto = bloque.replace(etiqueta, "", 1).strip(" :")
            if resto and not re.match(r"\d+\+", resto):  # "0+ 1+ 2+" = opciones de un filtro
                return resto
        return None

    def _descripcion(self, response) -> str | None:
        """Descripción completa. Primero el contenedor propio del sitio; si cambia de nombre,
        todo el texto entre el encabezado 'Descripción' y el siguiente encabezado."""
        caja = response.css(".clp-description-box")
        if caja:
            parrafos = [self._texto(p) for p in caja.xpath("./p")] or [self._texto(caja)]
            texto = "\n".join(p for p in parrafos if p)
            if texto:
                return texto
        titulo = response.xpath(
            "(//*[self::h2 or self::h3 or self::h4][normalize-space() = 'Descripción'])[1]"
        )
        if not titulo:
            return None
        nivel = titulo.xpath("name()").get()
        n = int(float(titulo.xpath(f"count(preceding::{nivel})").get())) + 1
        textos = titulo.xpath(
            f"following::text()[normalize-space()]"
            f"[not(ancestor::script or ancestor::style or ancestor::{nivel})]"
            f"[count(preceding::{nivel}) = $n]",
            n=n,
        ).getall()
        sobran = {"Ver descripción completa", "Ver menos"}
        texto = " ".join(t.strip() for t in textos if t.strip() not in sobran)
        return " ".join(texto.split()) or None

    @staticmethod
    def _fecha(texto: str | None):
        if not texto:
            return None
        m = re.search(r"\d{2}/\d{2}/\d{4}", texto)
        return datetime.strptime(m.group(0), "%d/%m/%Y").date() if m else None
