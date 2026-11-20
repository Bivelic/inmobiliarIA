"""Búsqueda y ordenamiento por relevancia (EDT 4.4.2, RF-04 y RF-05).

1. Filtros (se aplican tal cual): operación, tipo, comunas, precio (en CLP o UF), dormitorios,
   baños y m² mínimos.
2. Atributos pedidos (ej. acepta_mascotas = true) son PREFERENCIAS:
   - un aviso que dice lo contrario se excluye (ej. "no se aceptan mascotas");
   - uno que lo confirma suma puntaje, ponderado por la confianza de la IA;
   - uno que no lo menciona queda, pero más abajo.
3. Puntaje (0 a 1) = 0,70 × atributos + 0,20 × recencia + 0,10 × completitud
     atributos  = suma de coincidencias (con su confianza) / atributos pedidos
                  (1 si no se pidió ninguno; si la IA no respondió, relevancia por palabras)
     recencia   = e^(-días desde publicación / 30)
     completitud = parte de los datos básicos que trae el aviso (precio, dormitorios, baños,
                   m², comuna, descripción)
   Los pesos son una propuesta para los criterios de 3.2.2: se cambian en PESOS.
"""

import json
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

import psycopg

from core.ia.catalogo import Atributo
from core.ia.interpretacion import Criterios

PESOS = {"atributos": Decimal("0.70"), "recencia": Decimal("0.20"), "completitud": Decimal("0.10")}
DIAS_RECENCIA = 30
CONFIANZA_SIN_DATO = 0.7  # si la IA no informó confianza
LARGO_EXTRACTO = 280

ORDENES = {
    "relevancia": "puntaje DESC, id DESC",
    "recientes": "fecha_orden DESC, id DESC",
    "precio_asc": "precio_clp ASC NULLS LAST, id DESC",
    "precio_desc": "precio_clp DESC NULLS LAST, id DESC",
}

SQL = """
WITH pedidos AS (
    SELECT * FROM jsonb_to_recordset(%(pedidos)s::jsonb)
        AS x(atributo_id int, tipo text, valor_bool boolean, valor_num numeric, valor_texto text)
),
cand AS (
    SELECT p.id
    FROM publicacion p LEFT JOIN comuna c ON c.id = p.comuna_id
    WHERE {filtros}
),
atr AS (
    SELECT pa.publicacion_id,
           sum(CASE WHEN {coincide} THEN coalesce(pa.confianza, %(conf_def)s) ELSE 0 END)
               AS coincide,
           count(*) FILTER (WHERE x.tipo = 'booleano' AND pa.valor_bool <> x.valor_bool)
               AS contradice,
           array_agg(a.codigo ORDER BY a.id) FILTER (WHERE {coincide}) AS coincidencias
    FROM publicacion_atributo pa
    JOIN pedidos x ON x.atributo_id = pa.atributo_id
    JOIN atributo a ON a.id = pa.atributo_id
    WHERE pa.publicacion_id IN (SELECT id FROM cand)
    GROUP BY pa.publicacion_id
),
puntuado AS (
    SELECT p.id, po.codigo AS portal, p.url, p.operacion, p.tipo_propiedad, p.titulo,
           left(p.descripcion, %(largo)s) AS extracto,
           p.precio_clp, p.precio_uf, p.gastos_comunes_clp,
           c.nombre AS comuna, c.slug AS comuna_slug,
           p.dormitorios, p.banos, p.m2_util, p.m2_total, p.estacionamientos,
           p.fecha_publicacion, p.ultima_vez_visto,
           coalesce(p.fecha_publicacion::timestamptz, p.primera_vez_visto) AS fecha_orden,
           coalesce(atr.coincidencias, '{{}}') AS coincidencias,
           {s_atributos} AS s_atributos,
           exp(-greatest(extract(epoch FROM now()
                 - coalesce(p.fecha_publicacion::timestamptz, p.primera_vez_visto)), 0)
               / 86400.0 / %(dias)s) AS s_recencia,
           num_nonnulls(p.precio_clp, p.dormitorios, p.banos, coalesce(p.m2_total, p.m2_util),
                        p.comuna_id, p.descripcion) / 6.0 AS s_completitud
    FROM cand
    JOIN publicacion p ON p.id = cand.id
    JOIN portal po ON po.id = p.portal_id
    LEFT JOIN comuna c ON c.id = p.comuna_id
    LEFT JOIN atr ON atr.publicacion_id = p.id
    WHERE coalesce(atr.contradice, 0) = 0
)
SELECT *,
       round((%(p_atr)s * s_atributos + %(p_rec)s * s_recencia
              + %(p_comp)s * s_completitud)::numeric, 4) AS puntaje,
       count(*) OVER () AS total
FROM puntuado
ORDER BY {orden}
LIMIT %(limite)s OFFSET %(desde)s
"""

COINCIDE = """(
    (x.tipo = 'booleano' AND pa.valor_bool = x.valor_bool)
 OR (x.tipo = 'numero' AND pa.valor_num <= x.valor_num)
 OR (x.tipo = 'texto' AND lower(pa.valor_texto) LIKE '%%' || lower(x.valor_texto) || '%%')
)"""

TSV = "to_tsvector('spanish', p.titulo || ' ' || coalesce(p.descripcion, ''))"


@dataclass
class Pagina:
    total: int
    resultados: list[dict]


def _pedidos(criterios: Criterios, catalogo: list[Atributo]) -> list[dict]:
    por_codigo = {a.codigo: a for a in catalogo}
    pedidos = []
    for codigo, valor in criterios.atributos.items():
        a = por_codigo.get(codigo)
        if a is None:
            continue
        pedidos.append({
            "atributo_id": a.id,
            "tipo": a.tipo_dato,
            "valor_bool": valor if a.tipo_dato == "booleano" else None,
            "valor_num": float(valor) if a.tipo_dato == "numero" else None,
            "valor_texto": str(valor) if a.tipo_dato == "texto" else None,
        })
    return pedidos


def consulta_palabras(texto: str) -> str:
    """'depto Ñuñoa con perros' -> 'depto or ñuñoa or perros' (para websearch_to_tsquery)."""
    palabras = [p for p in re.findall(r"\w+", texto.lower()) if len(p) > 2 and not p.isdigit()]
    return " or ".join(palabras[:12])


def buscar(
    conn: psycopg.Connection,
    criterios: Criterios,
    catalogo: list[Atributo],
    *,
    texto_respaldo: str | None = None,
    orden: str = "relevancia",
    limite: int = 20,
    desde: int = 0,
) -> Pagina:
    """`texto_respaldo`: si la IA no interpretó el texto, se busca por palabras."""
    filtros = ["p.activa", "p.duplicado_de IS NULL", "p.operacion = %(operacion)s"]
    params: dict = {
        "operacion": criterios.operacion or "arriendo",
        "largo": LARGO_EXTRACTO,
        "dias": DIAS_RECENCIA,
        "conf_def": CONFIANZA_SIN_DATO,
        "p_atr": PESOS["atributos"],
        "p_rec": PESOS["recencia"],
        "p_comp": PESOS["completitud"],
        "limite": limite,
        "desde": desde,
    }
    if criterios.tipo_propiedad:
        filtros.append("p.tipo_propiedad = %(tipo)s")
        params["tipo"] = criterios.tipo_propiedad
    if criterios.comunas:
        filtros.append("c.slug = ANY(%(comunas)s)")
        params["comunas"] = criterios.comunas
    columna_precio = "p.precio_uf" if criterios.moneda == "UF" else "p.precio_clp"
    if criterios.precio_max is not None:
        filtros.append(f"{columna_precio} <= %(precio_max)s")
        params["precio_max"] = criterios.precio_max
    if criterios.precio_min is not None:
        filtros.append(f"{columna_precio} >= %(precio_min)s")
        params["precio_min"] = criterios.precio_min
    if criterios.dormitorios_min is not None:
        filtros.append("p.dormitorios >= %(dorm)s")
        params["dorm"] = criterios.dormitorios_min
    if criterios.banos_min is not None:
        filtros.append("p.banos >= %(banos)s")
        params["banos"] = criterios.banos_min
    if criterios.m2_min is not None:
        filtros.append("coalesce(p.m2_total, p.m2_util) >= %(m2)s")
        params["m2"] = criterios.m2_min

    pedidos = _pedidos(criterios, catalogo)
    params["pedidos"] = json.dumps(pedidos)
    if texto_respaldo and (q := consulta_palabras(texto_respaldo)):
        filtros.append(f"{TSV} @@ websearch_to_tsquery('spanish', %(q)s)")
        params["q"] = q
        s_atributos = f"least(ts_rank({TSV}, websearch_to_tsquery('spanish', %(q)s)) * 10, 1)"
    elif pedidos:
        s_atributos = f"coalesce(atr.coincide, 0) / {len(pedidos)}.0"
    else:
        s_atributos = "1.0"

    sql = SQL.format(
        filtros=" AND ".join(filtros),
        coincide=COINCIDE,
        s_atributos=s_atributos,
        orden=ORDENES.get(orden, ORDENES["relevancia"]),
    )
    filas = conn.execute(sql, params).fetchall()
    total = filas[0]["total"] if filas else 0
    for f in filas:
        for clave in ("total", "s_atributos", "s_recencia", "s_completitud", "fecha_orden"):
            f.pop(clave, None)
    return Pagina(total=total, resultados=filas)


def atributos_de(conn: psycopg.Connection, ids: list[int]) -> dict[int, list[dict]]:
    """Atributos de cada aviso, para mostrarlos en la web (RF-03.05 y RF-06.08)."""
    if not ids:
        return {}
    filas = conn.execute(
        """
        SELECT pa.publicacion_id, a.codigo, a.nombre, a.tipo_dato::text AS tipo,
               pa.valor_bool, pa.valor_num, pa.valor_texto, pa.confianza, pa.fuente::text AS fuente
        FROM publicacion_atributo pa JOIN atributo a ON a.id = pa.atributo_id
        WHERE pa.publicacion_id = ANY(%s)
        ORDER BY pa.publicacion_id, a.id
        """,
        (ids,),
    ).fetchall()
    resultado: dict[int, list[dict]] = {i: [] for i in ids}
    for f in filas:
        valores = (f["valor_bool"], f["valor_num"], f["valor_texto"])
        valor = next(v for v in valores if v is not None)
        resultado[f["publicacion_id"]].append({
            "codigo": f["codigo"],
            "nombre": f["nombre"],
            "tipo": f["tipo"],
            "valor": valor,
            "confianza": f["confianza"],
            "fuente": f["fuente"],
        })
    return resultado


# --------------------------------------------------------------------------- registro
def guardar_busqueda(
    conn: psycopg.Connection,
    texto: str,
    criterios: dict,
    n_resultados: int,
    duracion_ms: int,
    sesion_id: uuid.UUID | None = None,
    es_validacion: bool = False,
) -> int:
    return conn.execute(
        """
        INSERT INTO busqueda (sesion_id, texto, criterios, es_validacion, n_resultados, duracion_ms)
        VALUES (%s, %s, %s::jsonb, %s, %s, %s) RETURNING id
        """,
        (sesion_id or uuid.uuid4(), texto, json.dumps(criterios, default=str), es_validacion,
         n_resultados, duracion_ms),
    ).fetchone()["id"]


def guardar_resultados(
    conn: psycopg.Connection, busqueda_id: int, resultados: list[dict], desde: int = 0
) -> None:
    """Orden entregado: base para medir Precisión@10 (PT-007)."""
    for posicion, r in enumerate(resultados, start=desde + 1):
        conn.execute(
            """
            INSERT INTO resultado_busqueda (busqueda_id, posicion, publicacion_id, puntaje)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (busqueda_id, posicion, r["id"], r["puntaje"]),
        )
