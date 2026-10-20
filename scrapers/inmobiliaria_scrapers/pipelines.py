"""Pipeline común a todos los portales.

Por cada aviso que entrega un spider:
  1. lo valida con AvisoNormalizado (que además limpia datos personales),
  2. convierte el precio a CLP y UF y resuelve la comuna,
  3. lo inserta, lo actualiza si cambió, o solo marca que se vio hoy,
  4. lleva la cuenta para la tabla ejecucion_scraping (métrica de >= 95% sin error).

Un aviso con error se registra en error_scraping y la corrida sigue.
"""

import logging

import psycopg
from pydantic import ValidationError
from scrapy.exceptions import DropItem

from core.db import conectar
from core.indicadores import obtener_valor_uf
from core.modelos import AvisoNormalizado
from core.normalizacion import a_clp, a_uf, slug

log = logging.getLogger(__name__)

COLUMNAS = [
    "url", "operacion", "tipo_propiedad", "titulo", "descripcion",
    "precio_monto", "precio_moneda", "precio_clp", "precio_uf", "gastos_comunes_clp",
    "comuna_id", "sector", "latitud", "longitud",
    "dormitorios", "banos", "m2_util", "m2_total", "estacionamientos",
    "fecha_publicacion", "hash_contenido",
]


class GuardarEnBasePipeline:
    def open_spider(self, spider):
        self.conn = conectar(autocommit=True)
        fila = self.conn.execute(
            "SELECT id FROM portal WHERE codigo = %s", (spider.name,)
        ).fetchone()
        if not fila:
            raise RuntimeError(f"El portal '{spider.name}' no está en la tabla portal")
        self.portal_id = fila["id"]
        self.comunas = {
            f["slug"]: f["id"] for f in self.conn.execute("SELECT id, slug FROM comuna")
        }
        self.valor_uf = obtener_valor_uf()
        if self.valor_uf is None:
            log.warning("Sin valor de la UF: los precios en UF no se convertirán a CLP")
        self.cuenta = {"leidos": 0, "ok": 0, "error": 0, "nuevos": 0, "actualizados": 0}
        ejec = self.conn.execute(
            "INSERT INTO ejecucion_scraping (portal_id) VALUES (%s) RETURNING id, inicio",
            (self.portal_id,),
        ).fetchone()
        self.ejecucion_id, self.inicio = ejec["id"], ejec["inicio"]
        spider.logger.info(f"Ejecución {self.ejecucion_id} iniciada")

    # ------------------------------------------------------------------ avisos
    def process_item(self, item, spider):
        self.cuenta["leidos"] += 1
        datos = dict(item)
        url = str(datos.get("url", ""))
        try:
            aviso = AvisoNormalizado(**datos)
        except ValidationError as e:
            self._error(url, "validacion", str(e))
            raise DropItem(f"Aviso inválido: {url}") from e

        try:
            self._guardar(aviso)
        except psycopg.Error as e:
            self._error(url, "base", str(e))
            raise DropItem(f"No se pudo guardar: {url}") from e

        self.cuenta["ok"] += 1
        return item

    def _guardar(self, aviso: AvisoNormalizado) -> None:
        clp = aviso.precio_clp or a_clp(aviso.precio_monto, aviso.precio_moneda, self.valor_uf)
        uf = aviso.precio_uf or (
            aviso.precio_monto if aviso.precio_moneda == "UF" else a_uf(clp, self.valor_uf)
        )
        valores = aviso.model_dump(mode="python")
        valores.update(
            url=str(aviso.url),
            precio_clp=clp,
            precio_uf=uf,
            comuna_id=self.comunas.get(slug(aviso.comuna)) if aviso.comuna else None,
            hash_contenido=aviso.hash_contenido(),
        )

        actual = self.conn.execute(
            "SELECT id, hash_contenido FROM publicacion WHERE portal_id = %s AND id_externo = %s",
            (self.portal_id, aviso.id_externo),
        ).fetchone()

        if actual is None:
            cols = ", ".join(["portal_id", "id_externo", *COLUMNAS])
            marcas = ", ".join(["%s"] * (len(COLUMNAS) + 2))
            self.conn.execute(
                f"INSERT INTO publicacion ({cols}) VALUES ({marcas})",
                [self.portal_id, aviso.id_externo, *[valores[c] for c in COLUMNAS]],
            )
            self.cuenta["nuevos"] += 1
        elif actual["hash_contenido"] != valores["hash_contenido"]:
            asignaciones = ", ".join(f"{c} = %s" for c in COLUMNAS)
            self.conn.execute(
                f"UPDATE publicacion SET {asignaciones}, ultima_vez_visto = now(), "
                "activa = true, actualizado_en = now() WHERE id = %s",
                [*[valores[c] for c in COLUMNAS], actual["id"]],
            )
            self.cuenta["actualizados"] += 1
        else:
            self.conn.execute(
                "UPDATE publicacion SET ultima_vez_visto = now(), activa = true WHERE id = %s",
                (actual["id"],),
            )

    def _error(self, url: str, tipo: str, mensaje: str) -> None:
        self.cuenta["error"] += 1
        self.conn.execute(
            "INSERT INTO error_scraping (ejecucion_id, url, tipo, mensaje) VALUES (%s, %s, %s, %s)",
            (self.ejecucion_id, url or "(sin url)", tipo, mensaje[:2000]),
        )

    # ------------------------------------------------------------------ cierre
    def close_spider(self, spider, reason=None):
        # Errores de descarga o de lectura que el spider anotó (no llegaron como avisos)
        for url, tipo, mensaje in getattr(spider, "errores", []):
            self.cuenta["leidos"] += 1
            self._error(url, tipo, mensaje)

        terminada = reason in (None, "finished")
        bajas = 0
        # Las bajas solo se marcan en una corrida completa: si se limitó el número de páginas,
        # los avisos no visitados no desaparecieron del portal.
        if terminada and getattr(spider, "corrida_completa", False):
            bajas = self.conn.execute(
                "UPDATE publicacion SET activa = false "
                "WHERE portal_id = %s AND activa AND ultima_vez_visto < %s",
                (self.portal_id, self.inicio),
            ).rowcount

        c = self.cuenta
        if not terminada:
            estado = "fallida"
        elif c["error"] or not getattr(spider, "corrida_completa", False):
            estado = "parcial"
        else:
            estado = "ok"

        self.conn.execute(
            "UPDATE ejecucion_scraping SET fin = now(), estado = %s, paginas = %s, "
            "avisos_leidos = %s, avisos_ok = %s, avisos_error = %s, avisos_nuevos = %s, "
            "avisos_actualizados = %s, avisos_baja = %s WHERE id = %s",
            (estado, getattr(spider, "paginas_visitadas", 0), c["leidos"], c["ok"], c["error"],
             c["nuevos"], c["actualizados"], bajas, self.ejecucion_id),
        )
        pct = 100 * c["ok"] / c["leidos"] if c["leidos"] else 0
        spider.logger.info(
            f"Ejecución {self.ejecucion_id} ({estado}): {c['leidos']} leídos, {c['ok']} ok "
            f"({pct:.1f}%), {c['error']} con error, {c['nuevos']} nuevos, "
            f"{c['actualizados']} actualizados, {bajas} bajas"
        )
        self.conn.close()
