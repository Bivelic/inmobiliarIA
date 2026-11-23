# Buscador en lenguaje natural (EDT 4.4)

La persona escribe lo que busca ("depto en Ñuñoa que acepte perros bajo 600 mil"). La IA lo convierte en criterios, la base filtra los avisos y los ordena por qué tan bien calzan.

```
texto ──► core/ia/interpretacion.py ──► criterios (filtros + atributos pedidos)
              (IA, con caché)                 │
                                              ▼
                               core/buscador.py: filtra, excluye contradicciones,
                               calcula el puntaje y ordena (SQL)
                                              │
                                              ▼
                       GET /buscar ──► web (resultados, atributos y lo que se entendió)
```

## Cómo se ordena (criterios de 3.2.2)

- **Filtros** (se aplican tal cual): operación, tipo, comunas, precio (CLP o UF), dormitorios, baños y m² mínimos.
- **Atributos pedidos** ("acepte perros" = `acepta_mascotas`) son preferencias:
  - un aviso que dice lo contrario **se excluye** ("no se aceptan mascotas");
  - uno que lo confirma **sube**, según la confianza de la IA;
  - uno que no lo menciona **queda, pero más abajo**.
- **Puntaje** de 0 a 1 = **0,70 × atributos + 0,20 × recencia + 0,10 × completitud**.
  - atributos: coincidencias ponderadas por confianza ÷ atributos pedidos (1 si no se pidió ninguno);
  - recencia: e^(−días desde la publicación ÷ 30);
  - completitud: parte de los datos básicos que trae el aviso.

  Los pesos son una propuesta: se ajustan en `PESOS`, en `core/buscador.py`.
- Para `gastos_comunes_clp`, el valor pedido se trata como **máximo**. Para `estacion_metro`, basta con que el nombre esté contenido.

**Si la IA no responde** (sin claves, límite excedido o más de 2,2 segundos), se busca por palabras en el título y la descripción, y la respuesta lo avisa. La búsqueda nunca se cae por culpa de la IA. Además, cada interpretación se guarda: si el mismo texto se repite, no se vuelve a llamar a la IA.

## API para el frontend

`GET /buscar`

| Parámetro | Qué es |
| --- | --- |
| `q` | Texto escrito (opcional; sin texto se comporta como el listado) |
| `comuna`, `precio_max`, `dormitorios_min` | Filtros de la pantalla. **Mandan sobre** lo que se entendió del texto |
| `orden` | `relevancia` (por defecto), `recientes`, `precio_asc` o `precio_desc` |
| `limite`, `desde` | Paginación ("Cargar más": `desde` = avisos ya mostrados) |
| `busqueda_id` | En "Cargar más", el `busqueda_id` de la primera respuesta, para que el orden quede registrado |
| `sesion` | Un uuid por navegador (opcional, ej. `crypto.randomUUID()` guardado en una variable) |

Respuesta (resumida):

```json
{
  "busqueda_id": 42,
  "total": 37,
  "duracion_ms": 640,
  "interpretacion": {
    "interpretado": true,
    "desde_cache": false,
    "aviso": null,
    "resumen": ["Departamento", "en arriendo", "Ñuñoa", "hasta $600.000", "Acepta mascotas"],
    "criterios": {"comunas": ["nunoa"], "precio_max": 600000, "atributos": {"acepta_mascotas": true}}
  },
  "resultados": [
    {
      "id": 123, "portal": "yapo", "url": "https://...", "titulo": "...", "extracto": "...",
      "precio_clp": 550000, "comuna": "Ñuñoa", "dormitorios": 2, "banos": 1, "m2_total": 55,
      "puntaje": 0.8866,
      "coincidencias": ["acepta_mascotas"],
      "atributos": [{"codigo": "acepta_mascotas", "nombre": "Acepta mascotas", "valor": true}]
    }
  ]
}
```

Qué mostrar en la web:
- **`interpretacion.resumen`** como etiquetas sobre los resultados ("Buscamos: Ñuñoa · hasta $600.000 · Acepta mascotas"), para que la persona vea qué se entendió (RNF-04).
- Si **`interpretacion.aviso`** trae texto, mostrarlo en pequeño (ej. "se buscó por palabras").
- En cada aviso, los **`atributos`** como etiquetas (RF-06.08). Las que están en `coincidencias` van destacadas: son las que calzan con lo pedido. Un booleano `false` se muestra como "Sin …" o no se muestra.
- **`busqueda_id`** hay que guardarlo: se envía al pedir contacto, para el registro del lead (RF-07.03).

También hay:
- `GET /atributos`, con el catálogo de atributos (código, nombre y tipo);
- `GET /publicaciones/{id}`, que ahora incluye `atributos`.

## Puesta en marcha

1. En **Render**, en Environment, agrega `GEMINI_API_KEY`, `GROQ_API_KEY` e `IA_PROVEEDORES=gemini,groq`. Sin ellas, `/buscar` funciona, pero solo por palabras.
2. En **Neon**, `python scripts/init_db.py`, con el catálogo de atributos cargado.
3. Los avisos tienen que estar procesados por la IA (`scripts/extraer_atributos.py`). Si no, los atributos no ayudan a ordenar.

## Medir la calidad (PT-007 y PT-014)

```bash
python scripts/evaluar_busquedas.py generar busquedas.txt --salida p10.csv
#   (marcar la columna "relevante" con si / no)
python scripts/evaluar_busquedas.py calcular p10.csv
```

- `busquedas.txt` lleva una búsqueda por línea: las 20 de validación de 3.2.3.
- `generar` corre cada búsqueda con el mismo código que la web, la marca como de validación y muestra el tiempo de cada una. **El tiempo vale la primera vez**: después la interpretación sale de la caché.
- `calcular` guarda las marcas en `resultado_busqueda.relevante` y da la Precisión@10 de cada búsqueda y el promedio (meta ≥ 80%). Se divide siempre por 10, como dice PT-007.
