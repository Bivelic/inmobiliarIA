-- =====================================================================
-- Solicitud de cambio 1 · Panel de gestión de leads para ejecutivos de Aurora
-- IDEMPOTENTE: init_db.py la vuelve a correr cada vez, así que todo usa IF NOT EXISTS.
-- Agrega: estado 'cerrado', tabla de ejecutivos, ejecutivo asignado a cada lead, las fechas
-- que usan los indicadores y el historial de cambios (quién hizo qué y cuándo).
-- Los leads creados antes de esta migración no tienen fechas de respuesta ni de visita:
-- los indicadores son confiables solo para leads nuevos.
-- =====================================================================

ALTER TYPE estado_lead_t ADD VALUE IF NOT EXISTS 'cerrado';

-- Ejecutivos de Aurora que pueden entrar al panel (se crean con scripts/crear_ejecutivo.py)
CREATE TABLE IF NOT EXISTS ejecutivo (
    id             smallserial PRIMARY KEY,
    nombre         text NOT NULL,
    email          text NOT NULL UNIQUE CHECK (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),  -- siempre en minúscula
    password_hash  text NOT NULL,                -- scrypt; nunca la contraseña
    activo         boolean NOT NULL DEFAULT true,
    creado_en      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE lead
    ADD COLUMN IF NOT EXISTS ejecutivo_id         smallint REFERENCES ejecutivo(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS primera_respuesta_en timestamptz,   -- primera vez que pasó a contactado, visita_agendada o cerrado
    ADD COLUMN IF NOT EXISTS visita_agendada_en   timestamptz,   -- primera vez que llegó a visita_agendada
    ADD COLUMN IF NOT EXISTS actualizado_en       timestamptz NOT NULL DEFAULT now();

-- Historial: cada cambio de estado o de asignación queda registrado
CREATE TABLE IF NOT EXISTS lead_evento (
    id                    bigserial PRIMARY KEY,
    lead_id               bigint NOT NULL REFERENCES lead(id) ON DELETE CASCADE,
    ejecutivo_id          smallint REFERENCES ejecutivo(id) ON DELETE SET NULL,  -- quién hizo el cambio
    tipo                  text NOT NULL CHECK (tipo IN ('estado', 'asignacion')),
    estado_anterior       estado_lead_t,
    estado_nuevo          estado_lead_t,
    asignado_anterior_id  smallint,
    asignado_nuevo_id     smallint,
    creado_en             timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lead_creado_idx      ON lead (creado_en);
CREATE INDEX IF NOT EXISTS lead_estado_idx      ON lead (estado, creado_en DESC);
CREATE INDEX IF NOT EXISTS lead_ejecutivo_idx   ON lead (ejecutivo_id);
CREATE INDEX IF NOT EXISTS lead_evento_lead_idx ON lead_evento (lead_id, creado_en);
