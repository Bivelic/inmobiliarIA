"""Módulo de IA de InmobiliarIA (EDT 4.3).

- catalogo.py    : atributos a detectar, leídos de la tabla `atributo` (db/04_atributos.sql)
- prompt.py      : instrucciones para el modelo (versionadas) y formato de respuesta
- respuesta.py   : valida lo que responde el modelo; descarta lo que no está respaldado
- proveedores.py : llamadas a Gemini y Groq, con paso al siguiente si uno falla
- extraccion.py  : procesa los avisos pendientes en lotes y guarda el resultado
- evaluacion.py  : compara la IA con las etiquetas manuales (precisión >= 80%)
"""
