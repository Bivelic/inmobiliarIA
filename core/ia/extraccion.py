"""Extracción de atributos con IA sobre los avisos de la base (EDT 4.3.1, 4.3.2 y 4.3.3).

Flujo de una corrida:
  1. busca avisos pendientes: activos, no duplicados, con descripción, y sin una extracción
     exitosa para su texto actual (hash) y la versión actual del prompt;
  2. los manda al modelo en lotes (5 por llamada, por defecto);
  3. valida cada respuesta (respuesta.py) y guarda, por aviso, una fila en extraccion_ia y
     sus atributos en publicacion_atributo (fuente 'ia').

Control de costos (4.3.3): un aviso ya procesado no se vuelve a mandar mientras no cambie
su texto ni el prompt; cada corrida tiene un tope de avisos; se registran tokens y costo.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

import psycopg

from core.ia.catalogo import Atributo, cargar_catalogo
from core.ia.prompt import AvisoParaIA, instrucciones, mensaje_lote, version_prompt
from core.ia.proveedores import ClienteIA, ErrorProveedor, RespuestaModelo
from core.ia.respuesta import ResultadoAviso, validar_lote

log = logging.getLogger(__name__)

MIN_LARGO_DESCRIPCION = 20

SQL_PENDIENTES = """
WITH base AS (
    SELECT p.id, p.titulo, p.descripcion,
           encode(sha256(convert_to(p.titulo || E'\\n' || coalesce(p.descripcion, ''), 'UTF8')),
                  'hex') AS hash_entrada
    FROM publicacion p
    WHERE p.activa AND p.duplicado_de IS NULL
      AND length(coalesce(p.descripcion, '')) >= %(min_largo)s
      AND (%(ids)s::bigint[] IS NULL OR p.id = ANY(%(ids)s::bigint[]))
)
SELECT b.* FROM base b
WHERE %(forzar)s OR NOT EXISTS (
    SELECT 1 FROM extraccion_ia e
    WHERE e.publicacion_id = b.id AND e.exitosa
      AND e.version_prompt = %(version)s AND e.hash_entrada = b.hash_entrada
)
ORDER BY b.id
LIMIT %(limite)s
"""


@dataclass
class Pendiente:
    aviso: AvisoParaIA
    hash_entrada: str


@dataclass
class Resumen:
    version_prompt: str = ""
    pendientes: int = 0
    exitosos: int = 0
    fallidos: int = 0
    valores_guardados: int = 0
    descartados: int = 0
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: Decimal = Decimal(0)
    por_modelo: Counter = field(default_factory=Counter)
    motivos_descarte: Counter = field(default_factory=Counter)
    detenido_por: str | None = None


def avisos_pendientes(
    conn: psycopg.Connection,
    version: str,
    limite: int,
    ids: list[int] | None = None,
    forzar: bool = False,
) -> list[Pendiente]:
    filas = conn.execute(
        SQL_PENDIENTES,
        {
            "min_largo": MIN_LARGO_DESCRIPCION,
            "ids": ids,
            "forzar": forzar,
            "version": version,
            "limite": limite,
        },
    ).fetchall()
    return [
        Pendiente(AvisoParaIA(f["id"], f["titulo"], f["descripcion"]), f["hash_entrada"])
        for f in filas
    ]


def _guardar_aviso(
    conn: psycopg.Connection,
    pendiente: Pendiente,
    version: str,
    modelo: str,
    tokens: tuple[int | None, int | None],
    costo: Decimal | None,
    resultado: ResultadoAviso | None,
    error: str | None,
) -> int:
    """Guarda una extracción (exitosa o no) y, si fue exitosa, reemplaza sus atributos."""
    exitosa = resultado is not None and error is None
    extraccion_id = conn.execute(
        """
        INSERT INTO extraccion_ia (publicacion_id, modelo, version_prompt, hash_entrada,
                                   tokens_entrada, tokens_salida, costo_usd, exitosa, error)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (publicacion_id, modelo, version_prompt, hash_entrada) DO UPDATE
           SET tokens_entrada = EXCLUDED.tokens_entrada, tokens_salida = EXCLUDED.tokens_salida,
               costo_usd = EXCLUDED.costo_usd, exitosa = EXCLUDED.exitosa,
               error = EXCLUDED.error, creada_en = now()
        RETURNING id
        """,
        (pendiente.aviso.id, modelo, version, pendiente.hash_entrada, *tokens, costo,
         exitosa, error),
    ).fetchone()["id"]
    if not exitosa:
        return 0
    conn.execute(
        "DELETE FROM publicacion_atributo WHERE publicacion_id = %s AND fuente = 'ia'",
        (pendiente.aviso.id,),
    )
    for v in resultado.valores:
        conn.execute(
            """
            INSERT INTO publicacion_atributo (publicacion_id, atributo_id, fuente, valor_bool,
                valor_num, valor_texto, confianza, evidencia, extraccion_id)
            VALUES (%s, %s, 'ia', %s, %s, %s, %s, %s, %s)
            """,
            (
                pendiente.aviso.id,
                v.atributo_id,
                v.valor if v.tipo == "booleano" else None,
                v.valor if v.tipo == "numero" else None,
                v.valor if v.tipo == "texto" else None,
                v.confianza,
                v.evidencia,
                extraccion_id,
            ),
        )
    return len(resultado.valores)


class Extractor:
    def __init__(
        self,
        conn: psycopg.Connection,
        cliente: ClienteIA,
        catalogo: list[Atributo] | None = None,
        pausa: float = 2.0,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self.conn = conn  # conexión en modo autocommit: cada lote se guarda en su transacción
        self.cliente = cliente
        self.catalogo = catalogo or cargar_catalogo(conn)
        self.sistema = instrucciones(self.catalogo)
        self.version = version_prompt(self.catalogo)
        self.pausa = pausa
        self.dormir = dormir
        self.resumen = Resumen(version_prompt=self.version)

    # ----------------------------------------------------------------- corrida
    def correr(
        self,
        limite: int = 100,
        tamano_lote: int = 5,
        ids: list[int] | None = None,
        forzar: bool = False,
    ) -> Resumen:
        pendientes = avisos_pendientes(self.conn, self.version, limite, ids, forzar)
        self.resumen.pendientes = len(pendientes)
        lotes = [pendientes[i : i + tamano_lote] for i in range(0, len(pendientes), tamano_lote)]
        for n, lote in enumerate(lotes, start=1):
            log.info("Lote %d/%d (%d avisos)", n, len(lotes), len(lote))
            try:
                self._procesar_lote(lote, reintentar_sueltos=len(lote) > 1)
            except ErrorProveedor as e:
                self.resumen.detenido_por = str(e)
                log.error("Se detiene la corrida: %s", e)
                break
            if n < len(lotes) and self.pausa:
                self.dormir(self.pausa)
        return self.resumen

    def _llamar(self, lote: list[Pendiente]) -> RespuestaModelo:
        respuesta = self.cliente.completar(self.sistema, mensaje_lote([p.aviso for p in lote]))
        r = self.resumen
        r.llamadas += 1
        r.tokens_entrada += respuesta.tokens_entrada or 0
        r.tokens_salida += respuesta.tokens_salida or 0
        r.costo_usd += respuesta.costo_usd() or 0
        r.por_modelo[respuesta.nombre_modelo] += 1
        return respuesta

    def _procesar_lote(self, lote: list[Pendiente], reintentar_sueltos: bool) -> None:
        respuesta = self._llamar(lote)
        resultado = validar_lote(respuesta.texto, [p.aviso for p in lote], self.catalogo)

        n = len(lote)
        tokens = (
            round(respuesta.tokens_entrada / n) if respuesta.tokens_entrada else None,
            round(respuesta.tokens_salida / n) if respuesta.tokens_salida else None,
        )
        costo = respuesta.costo_usd()
        costo = (costo / n).quantize(Decimal("0.000001")) if costo is not None else None

        por_id = {p.aviso.id: p for p in lote}
        sin_resultado = [por_id[i] for i in resultado.faltantes]
        reintentar = bool(sin_resultado) and reintentar_sueltos

        with self.conn.transaction():
            for pid, res in resultado.avisos.items():
                guardados = _guardar_aviso(
                    self.conn, por_id[pid], self.version, respuesta.nombre_modelo, tokens,
                    costo, res, None,
                )
                self.resumen.exitosos += 1
                self.resumen.valores_guardados += guardados
                self.resumen.descartados += len(res.descartados)
                for motivo in res.descartados:
                    self.resumen.motivos_descarte[motivo.split(": ", 1)[-1]] += 1
            if not reintentar:
                for p in sin_resultado:
                    _guardar_aviso(
                        self.conn, p, self.version, respuesta.nombre_modelo, tokens, costo,
                        None, resultado.error or "el modelo no devolvió este aviso",
                    )
                    self.resumen.fallidos += 1

        if reintentar:
            # El modelo se confundió con el lote: esos avisos se reintentan de a uno.
            log.warning("%d avisos sin respuesta válida; van de a uno", len(sin_resultado))
            for p in sin_resultado:
                self._procesar_lote([p], reintentar_sueltos=False)
