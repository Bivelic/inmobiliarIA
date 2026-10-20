-- Portales agregados después del esquema inicial. Se puede correr las veces que sea.
INSERT INTO portal (codigo, nombre, url_base, delay_seg) VALUES
  ('toctoc', 'TocToc', 'https://www.toctoc.com', 2)
ON CONFLICT (codigo) DO NOTHING;
