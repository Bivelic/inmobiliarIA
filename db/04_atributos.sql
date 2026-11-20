-- =====================================================================
-- Catálogo de atributos que la IA busca en las descripciones (EDT 2.1.1)
--
-- PROVISORIO: lista propuesta por el equipo técnico a partir de la EDT y el caso
-- de negocio, a la espera de la lista priorizada con Aurora. Para cambiarla:
-- editar este archivo y correr `python scripts/init_db.py` (local y Neon).
--
-- La "descripcion" de cada atributo se copia tal cual en el prompt: es la regla
-- que sigue la IA, así que debe ser concreta y decir qué NO cuenta.
-- Se puede correr muchas veces: actualiza nombre, tipo y descripción por código.
-- =====================================================================

INSERT INTO atributo (codigo, nombre, tipo_dato, descripcion) VALUES
  ('acepta_mascotas', 'Acepta mascotas', 'booleano',
   'true si el aviso dice que se aceptan o permiten mascotas (perros, gatos); false si dice que no se aceptan. Un "pet friendly" cuenta como true.'),
  ('amoblado', 'Amoblado', 'booleano',
   'true si se entrega amoblado o semi amoblado; false si dice explícitamente que se entrega sin muebles. Cocina equipada o closets por sí solos no cuentan.'),
  ('cerca_metro', 'Cerca del metro', 'booleano',
   'true si el aviso dice que está cerca, a pasos o a una distancia caminable (hasta unas 10 cuadras o 15 minutos a pie) de una estación de metro. Mencionar solo la comuna o el barrio no cuenta.'),
  ('estacion_metro', 'Estación de metro cercana', 'texto',
   'Nombre de la estación de metro que el aviso menciona como cercana, sin la palabra "metro" ni la línea (ej.: "Ñuble", "Los Leones"). Si menciona varias, la primera.'),
  ('estacionamiento', 'Estacionamiento', 'booleano',
   'true si el arriendo o la venta incluye estacionamiento propio o asignado; false si dice que no incluye estacionamiento. Estacionamiento de visitas del edificio no cuenta.'),
  ('bodega', 'Bodega', 'booleano',
   'true si incluye bodega; false si dice que no incluye bodega.'),
  ('gastos_comunes_clp', 'Gastos comunes (CLP)', 'numero',
   'Monto mensual de gastos comunes en pesos chilenos, como número sin puntos ni símbolo (ej.: 85000). Si viene en UF o es un rango, no lo informes.'),
  ('terraza', 'Terraza o balcón', 'booleano',
   'true si la propiedad tiene terraza, balcón o patio privado. Terrazas o quinchos comunes del edificio no cuentan.'),
  ('piscina', 'Piscina', 'booleano',
   'true si la propiedad o el edificio/condominio tiene piscina disponible para los residentes.'),
  ('quincho', 'Quincho', 'booleano',
   'true si la propiedad o el edificio/condominio tiene quincho o zona de parrillas.'),
  ('gimnasio', 'Gimnasio', 'booleano',
   'true si el edificio o condominio tiene gimnasio para los residentes.'),
  ('conserjeria', 'Conserjería', 'booleano',
   'true si el edificio o condominio tiene conserjería o portería (24 horas o parcial).'),
  ('logia', 'Logia', 'booleano',
   'true si la propiedad tiene logia (espacio para lavadora separado de la cocina).'),
  ('calefaccion', 'Calefacción', 'booleano',
   'true si la propiedad tiene un sistema de calefacción (central, losa radiante, eléctrica instalada, etc.). Solo "buena aislación" no cuenta.'),
  ('orientacion', 'Orientación', 'texto',
   'Orientación de la propiedad, usando solo uno de estos valores: norte, sur, oriente, poniente, nororiente, norponiente, suroriente, surponiente.')
ON CONFLICT (codigo) DO UPDATE
   SET nombre = EXCLUDED.nombre,
       tipo_dato = EXCLUDED.tipo_dato,
       descripcion = EXCLUDED.descripcion;
