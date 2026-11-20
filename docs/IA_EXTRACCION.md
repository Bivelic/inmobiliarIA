# Extracción de atributos con IA (EDT 4.3)

La IA lee el título y la descripción de cada aviso y guarda los atributos que el texto menciona de forma explícita ("acepta mascotas", "cerca del metro", "gastos comunes $85.000"…). Esos atributos son los que después usan el buscador en lenguaje natural (4.4) y la web.

```
publicacion ──► scripts/extraer_atributos.py ──► Gemini (o Groq si Gemini está ocupado)
                     │                                   │
                     │       respuesta en JSON  ◄────────┘
                     ▼
              core/ia/respuesta.py  (descarta lo que no está respaldado por el texto)
                     ▼
     extraccion_ia (una fila por aviso: modelo, versión, tokens)
     publicacion_atributo (fuente 'ia': valor, confianza, evidencia)
```

## 1. Configurar (una vez)

Las dos claves son gratis. Basta con una, pero con las dos la corrida no se detiene si una llega a su límite.

| Proveedor | Dónde se crea la clave | Variable en el `.env` |
| --- | --- | --- |
| Google Gemini (principal) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GEMINI_API_KEY` |
| Groq (respaldo) | [console.groq.com/keys](https://console.groq.com/keys) | `GROQ_API_KEY` |

Copia las variables nuevas de `.env.example` a tu `.env` y pega las claves. **Nunca** las subas al repositorio.

Luego carga el catálogo de atributos en la base (local y Neon):

```bash
python scripts/init_db.py
```

## 2. Correr la extracción

Desde la raíz, con el entorno virtual activo:

```bash
python scripts/extraer_atributos.py --ver-prompt     # muestra el prompt; NO llama a la IA
python scripts/extraer_atributos.py --limite 20      # prueba corta
python scripts/extraer_atributos.py --limite 500     # corrida grande
```

Al final muestra cuántos avisos procesó, cuántos atributos guardó o descartó, los tokens y cuántos quedan pendientes. Se puede correr las veces que haga falta: un aviso ya procesado **no se vuelve a mandar** mientras no cambie su texto ni el prompt.

Opciones útiles:

| Opción | Para qué |
| --- | --- |
| `--limite N` | Máximo de avisos en esta corrida (por defecto 100) |
| `--lote N` | Avisos por llamada (por defecto 5) |
| `--pausa S` | Segundos entre llamadas (por defecto 2) |
| `--proveedores groq` | Usar solo un proveedor |
| `--csv validacion.csv` | Procesar solo los avisos del conjunto de validación |
| `--ids 12,15 --forzar` | Reprocesar avisos puntuales |

Para revisar el resultado en la base:

```sql
SELECT p.titulo, a.codigo, pa.valor_bool, pa.valor_num, pa.valor_texto, pa.evidencia
FROM publicacion_atributo pa
JOIN atributo a ON a.id = pa.atributo_id
JOIN publicacion p ON p.id = pa.publicacion_id
WHERE pa.fuente = 'ia'
ORDER BY p.id DESC LIMIT 30;
```

## 3. Conjunto de validación y precisión (3.2.3 y criterio de 4.3)

El criterio de aceptación de 4.3 es **precisión ≥ 80%** sobre 200 avisos etiquetados a mano.

1. **Generar la plantilla** con avisos de la misma base donde corre la IA (normalmente Neon):
   ```bash
   python scripts/plantilla_etiquetado.py --n 200 --salida validacion.csv
   ```
2. **Etiquetar** en Excel o Google Sheets. Por cada aviso, solo lo que el texto dice de forma explícita:
   - booleano: `si`, `no` o vacío (vacío = el aviso no lo menciona);
   - número: el monto, por ejemplo `85000` (también sirve `85.000`);
   - texto: por ejemplo `Los Leones`;
   - en `etiquetado_por`, el nombre de quien la llenó.

   No cambies `publicacion_id`. Se puede repartir el archivo entre varias personas y juntarlo después.
3. **Extraer esos avisos** y **evaluar**:
   ```bash
   python scripts/extraer_atributos.py --csv validacion.csv
   python scripts/evaluar_extraccion.py validacion.csv --detalle
   ```
4. Si la precisión no llega a 80%, revisa las diferencias que lista `--detalle` y ajusta las definiciones en `db/04_atributos.sql` o las reglas en `core/ia/prompt.py`. Corre `init_db.py` si cambiaste el catálogo. La versión del prompt cambia sola, así que la próxima extracción reprocesa todo.
5. Con `--guardar` las etiquetas se copian a la tabla `etiqueta_manual`, como respaldo en la base.

Qué mide cada columna de la evaluación:

| Medida | Significa |
| --- | --- |
| **Precisión** | De lo que informó la IA, cuánto es correcto. Es el criterio de 4.3 |
| **Cobertura** | De lo que dicen las etiquetas, cuánto encontró la IA |
| **Inventados** | La IA informó algo que el aviso no menciona (debería ser 0, RF-03.06) |
| **Omitidos** | El aviso lo menciona y la IA no lo encontró |

Los números se dan por iguales con 1% de diferencia; los textos, sin importar mayúsculas ni tildes.

## 4. Cambiar la lista de atributos

La lista de `db/04_atributos.sql` es **provisoria** hasta tener la lista priorizada con Aurora (2.1.1). Para cambiarla:

1. Edita el archivo: agrega filas o cambia nombres, tipos o definiciones. La definición se copia tal cual en el prompt, así que debe ser concreta y decir qué **no** cuenta.
2. Corre `python scripts/init_db.py` en local y en Neon.
3. Para **quitar** un atributo, bórralo a mano: `DELETE FROM atributo WHERE codigo = '...';` (borra antes sus filas en `publicacion_atributo` y `etiqueta_manual`).
4. Genera de nuevo la plantilla de etiquetado si cambiaron las columnas.

## 5. Cómo cumple los requerimientos

- **No inventar (RF-03.06):** el prompt pide solo lo explícito, y además cada valor debe venir con una "evidencia" que se busca en el texto real del aviso. Si no está, el valor se descarta y se cuenta.
- **Control de costos (4.3.3):** los avisos ya procesados no se reenvían, cada corrida tiene un tope (`--limite`) y se registran tokens y costo en `extraccion_ia`. La columna `costo_usd` es lo que costaría en el plan pagado: sirve de referencia para el presupuesto, porque en el plan gratuito el gasto real es 0.
- **Cambio de proveedor (riesgo R-11):** el resto del código no sabe qué modelo se usa. Para cambiarlo basta con editar `IA_PROVEEDORES` o `IA_MODELO_*` en el `.env`.
- **Datos personales:** a la IA solo se envían título y descripción, que ya vienen sin teléfonos, correos ni RUT (`core/limpieza.py`).

## 6. Problemas comunes

| Mensaje | Qué hacer |
| --- | --- |
| `No hay ningún proveedor de IA con clave` | Falta `GEMINI_API_KEY` o `GROQ_API_KEY` en el `.env` |
| `gemini respondió 404` | El nombre del modelo cambió: copia el nombre exacto desde AI Studio en `IA_MODELO_GEMINI` |
| `límite excedido` | Normal en el plan gratis: pasa al otro proveedor o espera solo. Si se detiene, vuelve a correr más tarde; sigue donde quedó |
| `La tabla atributo está vacía` | Corre `python scripts/init_db.py` |
| `avisos del CSV no están en esta base` | La plantilla se generó con otra base (local vs Neon): usa la misma `DATABASE_URL` |
