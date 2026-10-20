-- =====================================================================
-- InmobiliarIA · Grupo 10 · Esquema de base de datos (EDT 3.1.3)
-- PostgreSQL 16 · v1.0 · 05/10/2026
--
-- Organizado por hito:
--   Bloque A (H2) núcleo de scraping y normalización  -> implementar ya
--   Bloque B (H3) extracción de atributos con IA
--   Bloque C (H3-H4) búsquedas, evaluación de relevancia y leads
--
-- Regla de datos personales (Ley 21.719): ninguna tabla de los bloques A
-- y B guarda nombre, teléfono, correo ni RUT del publicante. La única
-- tabla con datos personales es "lead" (bloque C), con consentimiento.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- similitud de texto (duplicados)
-- CREATE EXTENSION IF NOT EXISTS vector; -- pgvector: activar en H3 si el
--                                        -- ranking usa búsqueda semántica

-- ---------------------------------------------------------------------
-- Tipos enumerados
-- ---------------------------------------------------------------------
CREATE TYPE operacion_t      AS ENUM ('arriendo', 'venta');
CREATE TYPE tipo_propiedad_t AS ENUM ('departamento', 'casa', 'estudio', 'otro');
CREATE TYPE moneda_t         AS ENUM ('CLP', 'UF', 'USD');
CREATE TYPE estado_ejec_t    AS ENUM ('en_curso', 'ok', 'parcial', 'fallida');
CREATE TYPE tipo_dato_t      AS ENUM ('booleano', 'numero', 'texto');
CREATE TYPE fuente_attr_t    AS ENUM ('portal', 'ia', 'manual');
CREATE TYPE estado_lead_t    AS ENUM ('nuevo', 'contactado', 'visita_agendada', 'descartado');

-- =====================================================================
-- BLOQUE A · H2 · Scraping y normalización (paquetes 4.1 y 4.2)
-- =====================================================================

-- Portales fuente seleccionados en 2.1.2
CREATE TABLE portal (
    id          smallserial PRIMARY KEY,
    codigo      text NOT NULL UNIQUE,            -- 'chilepropiedades', 'yapo', 'economicos'
    nombre      text NOT NULL,
    url_base    text NOT NULL,
    activo      boolean NOT NULL DEFAULT true,   -- false = portal descartado o bloqueado
    delay_seg   numeric(4,1) NOT NULL DEFAULT 2  -- pausa entre requests (robots.txt)
);

-- Diccionario de comunas para normalizar ("Ñuñoa", "nunoa", "NUÑOA" -> 1 fila)
CREATE TABLE comuna (
    id          smallserial PRIMARY KEY,
    nombre      text NOT NULL UNIQUE,            -- forma canónica: 'Ñuñoa'
    slug        text NOT NULL UNIQUE,            -- 'nunoa'
    region      text NOT NULL
);

-- Bitácora de cada corrida de un scraper: da la métrica de ≥95% sin error
CREATE TABLE ejecucion_scraping (
    id               bigserial PRIMARY KEY,
    portal_id        smallint NOT NULL REFERENCES portal(id),
    inicio           timestamptz NOT NULL DEFAULT now(),
    fin              timestamptz,
    estado           estado_ejec_t NOT NULL DEFAULT 'en_curso',
    paginas          integer NOT NULL DEFAULT 0,
    avisos_leidos    integer NOT NULL DEFAULT 0,  -- intentados
    avisos_ok        integer NOT NULL DEFAULT 0,  -- parseados y validados
    avisos_error     integer NOT NULL DEFAULT 0,
    avisos_nuevos    integer NOT NULL DEFAULT 0,
    avisos_actualizados integer NOT NULL DEFAULT 0,
    avisos_baja      integer NOT NULL DEFAULT 0,  -- desaparecieron del portal
    CHECK (avisos_ok + avisos_error <= avisos_leidos)
);

-- Detalle de cada aviso que no se pudo leer (para depurar scrapers)
CREATE TABLE error_scraping (
    id             bigserial PRIMARY KEY,
    ejecucion_id   bigint NOT NULL REFERENCES ejecucion_scraping(id) ON DELETE CASCADE,
    url            text NOT NULL,
    tipo           text NOT NULL,                -- 'http', 'parseo', 'validacion'
    mensaje        text,
    ocurrido_en    timestamptz NOT NULL DEFAULT now()
);

-- Aviso normalizado: el "formato común" sin importar el portal
CREATE TABLE publicacion (
    id                  bigserial PRIMARY KEY,
    portal_id           smallint NOT NULL REFERENCES portal(id),
    id_externo          text NOT NULL,           -- código del aviso en el portal
    url                 text NOT NULL,           -- enlace al aviso original (siempre se muestra)
    operacion           operacion_t NOT NULL,
    tipo_propiedad      tipo_propiedad_t NOT NULL,
    titulo              text NOT NULL,
    descripcion         text,                    -- YA LIMPIA de teléfonos, correos, RUT y nombres
    -- precio tal como venía + valores normalizados
    precio_monto        numeric(14,2) NOT NULL CHECK (precio_monto > 0),
    precio_moneda       moneda_t NOT NULL,
    precio_clp          numeric(14,0),           -- convertido con el valor UF/USD del día
    precio_uf           numeric(10,2),
    gastos_comunes_clp  numeric(12,0) CHECK (gastos_comunes_clp >= 0),
    -- ubicación (sin dirección exacta del particular)
    comuna_id           smallint REFERENCES comuna(id),
    sector              text,                    -- texto libre: 'Barrio Italia', 'Metro Santa Isabel'
    latitud             numeric(9,6),
    longitud            numeric(9,6),
    -- campos estructurados que trae el portal (pueden venir vacíos o mal)
    dormitorios         smallint CHECK (dormitorios BETWEEN 0 AND 20),
    banos               smallint CHECK (banos BETWEEN 0 AND 20),
    m2_util             numeric(8,2) CHECK (m2_util > 0),
    m2_total            numeric(8,2) CHECK (m2_total > 0),
    estacionamientos    smallint CHECK (estacionamientos >= 0),
    -- ciclo de vida
    fecha_publicacion   date,                    -- según el portal
    primera_vez_visto   timestamptz NOT NULL DEFAULT now(),
    ultima_vez_visto    timestamptz NOT NULL DEFAULT now(),
    activa              boolean NOT NULL DEFAULT true,   -- false = ya no está en el portal
    hash_contenido      text NOT NULL,           -- detecta cambios sin comparar campo a campo
    -- duplicados entre portales (4.2.3): apunta a la publicación "canónica"
    duplicado_de        bigint REFERENCES publicacion(id) ON DELETE SET NULL,
    actualizado_en      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (portal_id, id_externo),
    CHECK (duplicado_de IS NULL OR duplicado_de <> id)
);

CREATE INDEX publicacion_busqueda_idx
    ON publicacion (operacion, tipo_propiedad, comuna_id, precio_clp)
    WHERE activa AND duplicado_de IS NULL;
CREATE INDEX publicacion_titulo_trgm_idx
    ON publicacion USING gin (titulo gin_trgm_ops);
CREATE INDEX publicacion_ultima_vez_idx ON publicacion (portal_id, ultima_vez_visto);

-- =====================================================================
-- BLOQUE B · H3 · Extracción de atributos con IA (paquetes 2.1.1, 3.2, 4.3)
-- =====================================================================

-- Catálogo de los ~15 atributos acordados con Aurora (2.1.1)
CREATE TABLE atributo (
    id           smallserial PRIMARY KEY,
    codigo       text NOT NULL UNIQUE,           -- 'acepta_mascotas', 'cerca_metro', 'amoblado'
    nombre       text NOT NULL,
    tipo_dato    tipo_dato_t NOT NULL,
    descripcion  text NOT NULL                   -- definición que también va en el prompt
);

-- Cada llamada al LLM: control de costos (4.3.3) y caché por hash de descripción
CREATE TABLE extraccion_ia (
    id               bigserial PRIMARY KEY,
    publicacion_id   bigint NOT NULL REFERENCES publicacion(id) ON DELETE CASCADE,
    modelo           text NOT NULL,
    version_prompt   text NOT NULL,
    hash_entrada     text NOT NULL,              -- igual hash + modelo + prompt = no se vuelve a llamar
    tokens_entrada   integer,
    tokens_salida    integer,
    costo_usd        numeric(10,6),
    exitosa          boolean NOT NULL,
    error            text,
    creada_en        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (publicacion_id, modelo, version_prompt, hash_entrada)
);

-- Valor de cada atributo por publicación, según su fuente
CREATE TABLE publicacion_atributo (
    publicacion_id   bigint   NOT NULL REFERENCES publicacion(id) ON DELETE CASCADE,
    atributo_id      smallint NOT NULL REFERENCES atributo(id),
    fuente           fuente_attr_t NOT NULL,     -- 'portal' (campo), 'ia' (descripción)
    valor_bool       boolean,
    valor_num        numeric(12,2),
    valor_texto      text,
    confianza        numeric(3,2) CHECK (confianza BETWEEN 0 AND 1),
    evidencia        text,                       -- fragmento corto de la descripción que lo respalda
    extraccion_id    bigint REFERENCES extraccion_ia(id) ON DELETE SET NULL,
    PRIMARY KEY (publicacion_id, atributo_id, fuente),
    CHECK (num_nonnulls(valor_bool, valor_num, valor_texto) = 1),
    CHECK (fuente <> 'ia' OR extraccion_id IS NOT NULL)
);
CREATE INDEX publicacion_atributo_filtro_idx
    ON publicacion_atributo (atributo_id, valor_bool) WHERE valor_bool IS NOT NULL;

-- Conjunto de validación (3.2.4): 200 publicaciones etiquetadas a mano
CREATE TABLE etiqueta_manual (
    publicacion_id   bigint   NOT NULL REFERENCES publicacion(id) ON DELETE CASCADE,
    atributo_id      smallint NOT NULL REFERENCES atributo(id),
    valor_bool       boolean,
    valor_num        numeric(12,2),
    valor_texto      text,
    etiquetado_por   text NOT NULL,              -- integrante del equipo
    etiquetado_en    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (publicacion_id, atributo_id),
    CHECK (num_nonnulls(valor_bool, valor_num, valor_texto) = 1)
);

-- =====================================================================
-- BLOQUE C · H3-H4 · Búsqueda, relevancia y leads (paquetes 4.4, 4.5, 5.3.3)
-- =====================================================================

-- Cada búsqueda escrita por un usuario y cómo la interpretó el sistema
CREATE TABLE busqueda (
    id               bigserial PRIMARY KEY,
    sesion_id        uuid NOT NULL,              -- anónima, sin login
    texto            text NOT NULL,              -- "depto cerca del metro que acepte perros"
    criterios        jsonb NOT NULL DEFAULT '{}',-- interpretación: filtros + preferencias
    es_validacion    boolean NOT NULL DEFAULT false, -- una de las 20 búsquedas de 3.2.4
    n_resultados     integer,
    duracion_ms      integer,                    -- tiempo de respuesta (meta < 3 s)
    creada_en        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX busqueda_sesion_idx ON busqueda (sesion_id, creada_en);

-- Resultados entregados, en orden, y si el usuario o evaluador los marcó relevantes
CREATE TABLE resultado_busqueda (
    busqueda_id      bigint NOT NULL REFERENCES busqueda(id) ON DELETE CASCADE,
    posicion         smallint NOT NULL CHECK (posicion >= 1),
    publicacion_id   bigint NOT NULL REFERENCES publicacion(id) ON DELETE CASCADE,
    puntaje          numeric(6,4) NOT NULL,
    relevante        boolean,                    -- null = no evaluado; base de precisión@10
    PRIMARY KEY (busqueda_id, posicion),
    UNIQUE (busqueda_id, publicacion_id)
);

-- Solicitudes de contacto a Aurora (4.5.3): métrica de +20% de contactos
-- ÚNICA tabla con datos personales: se guardan con consentimiento explícito
CREATE TABLE lead (
    id               bigserial PRIMARY KEY,
    publicacion_id   bigint REFERENCES publicacion(id) ON DELETE SET NULL,
    busqueda_id      bigint REFERENCES busqueda(id) ON DELETE SET NULL,
    nombre           text NOT NULL,
    email            text NOT NULL CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    telefono         text,
    mensaje          text,
    consentimiento   boolean NOT NULL CHECK (consentimiento),
    estado           estado_lead_t NOT NULL DEFAULT 'nuevo',
    creado_en        timestamptz NOT NULL DEFAULT now(),
    eliminar_desde   timestamptz NOT NULL DEFAULT now() + interval '12 months'
);

-- =====================================================================
-- Vistas de métricas
-- =====================================================================

-- % de avisos leídos sin error por ejecución (criterio de aceptación de 4.1)
CREATE VIEW v_tasa_exito_scraping AS
SELECT e.id, p.codigo AS portal, e.inicio, e.avisos_leidos, e.avisos_ok,
       round(100.0 * e.avisos_ok / NULLIF(e.avisos_leidos, 0), 1) AS pct_ok
FROM ejecucion_scraping e JOIN portal p ON p.id = e.portal_id;

-- Precisión@10 por búsqueda evaluada (objetivo de calidad ≥ 80%)
CREATE VIEW v_precision_at_10 AS
SELECT busqueda_id,
       round(100.0 * count(*) FILTER (WHERE relevante) / count(*), 1) AS precision_at_10
FROM resultado_busqueda
WHERE posicion <= 10 AND relevante IS NOT NULL
GROUP BY busqueda_id;

-- =====================================================================
-- Datos iniciales
-- =====================================================================
INSERT INTO portal (codigo, nombre, url_base, delay_seg) VALUES
  ('chilepropiedades', 'Chilepropiedades', 'https://chilepropiedades.cl', 2),
  ('yapo',             'Yapo',             'https://www.yapo.cl',         2),
  ('economicos',       'Economicos',       'https://www.economicos.cl',   2)
ON CONFLICT (codigo) DO NOTHING;
