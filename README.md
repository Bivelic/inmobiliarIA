# InmobiliarIA · Grupo 10

Plataforma web que reúne avisos de arriendo de varios portales chilenos y usa IA para encontrar lo que los filtros no capturan. Proyecto de Sextante Digital SpA para Aurora Propiedades (IIC3113).

**Estado al 20/10/2026:** dos portales funcionando y guardando en la misma base: **Chilepropiedades** (Scrapy, verificado contra una ficha real) y **TocToc** (`property_search`). Además están la API y un frontend mínimo, todo conectado y con pruebas. Faltan Yapo o Economicos como tercer portal y el módulo de IA (H3).

---

## Qué hay en el repositorio

```
inmobiliaria/
├── core/                       Código compartido por scrapers y API
│   ├── config.py               Lee el archivo .env
│   ├── db.py                   Conexión a PostgreSQL
│   ├── modelos.py              AvisoNormalizado: formato común de un aviso + validaciones
│   ├── limpieza.py             Quita teléfonos, correos, RUT y nombres de las descripciones
│   ├── normalizacion.py        Precios, números y comunas al formato común
│   ├── guardado.py             Guarda los avisos: inserta/actualiza, errores, conteos y bajas
│   └── indicadores.py          Valor de la UF del día
├── db/
│   ├── 01_schema.sql           Las 12 tablas, vistas de métricas y portales iniciales
│   ├── 02_comunas.sql          Las 52 comunas de la Región Metropolitana
│   └── 03_portales_extra.sql   Portales agregados después (TocToc)
├── scrapers/
│   ├── inmobiliaria_scrapers/  Proyecto Scrapy
│   │   ├── settings.py         Reglas de cortesía: robots.txt, pausa de 2 s, User-Agent honesto
│   │   ├── pipelines.py        Pasa cada aviso a core/guardado.py
│   │   └── spiders/
│   │       ├── base.py              Clase base para los spiders
│   │       └── chilepropiedades.py  Lee el JSON-LD de cada ficha (verificado 20/10)
│   ├── property_search/        SIN modificar (TocToc)
│   └── cargar_property_search.py  Adaptador: corre property_search y guarda en la base
├── api/main.py                 API FastAPI: /publicaciones, /comunas, /metricas, /health
├── web/                        Frontend React + TypeScript + Vite
├── scripts/
│   ├── init_db.py              Crea las tablas o carga los datos iniciales nuevos
│   ├── check_setup.py          Verifica que todo esté listo
│   └── resumen.py              Avisos y estado de la última ejecución, por portal
├── tests/                      Pruebas con pytest
│   └── fixtures/               Páginas guardadas para probar sin conexión
├── docker-compose.yml          PostgreSQL 16 local
└── .github/workflows/ci.yml    Revisa cada push: estilo, pruebas y build
```

### Cómo fluyen los datos

```
Chilepropiedades ──► spider Scrapy ─────────────┐
                                                ├──► core/guardado.py ──► PostgreSQL ──► API ──► web
TocToc ──► property_search ──► adaptador ───────┘    (valida, limpia datos personales,
                                                      convierte precios, cuenta errores)
```

Los dos scrapers terminan en `core/guardado.py`, así que todos los portales se validan, se limpian y se miden igual.

---

## Paso 1 · Instalar los programas (una vez por computador)

| Programa | Versión | Para qué | Cómo comprobar |
| --- | --- | --- | --- |
| [Git](https://git-scm.com/downloads) | cualquiera reciente | Control de versiones | `git --version` |
| [Python](https://www.python.org/downloads/) | 3.11 o más (recomendado 3.12) | Scrapers, API | `python --version` (Windows) o `python3 --version` (Mac/Linux) |
| [Node.js](https://nodejs.org/) | 22 LTS | Frontend | `node --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | opcional | Base de datos local | `docker --version` |

En Windows, al instalar Python marca la casilla **"Add python.exe to PATH"**. Docker es opcional: sin él se trabaja directo contra Neon (Paso 5, opción B).

---

## Paso 2 · Crear el repositorio en GitHub (solo UNA persona del equipo)

1. En [github.com/new](https://github.com/new) crea un repositorio **privado** llamado `inmobiliaria`, **sin** README ni `.gitignore`.
2. Dentro de la carpeta del proyecto:

   ```bash
   git init
   git add .
   git commit -m "Base del proyecto"
   git branch -M main
   git remote add origin https://github.com/<usuario-u-organizacion>/inmobiliaria.git
   git push -u origin main
   ```

3. En GitHub: **Settings → Collaborators → Add people**, y agrega al equipo.
4. Revisa la pestaña **Actions**: el CI debe quedar en verde.

`scrapers/property_search/` no debe tener una carpeta `.git` propia (un repositorio dentro de otro). Si la tiene, bórrala antes del primer commit.

---

## Paso 3 · Clonar el repositorio (cada integrante)

```bash
git clone https://github.com/<usuario-u-organizacion>/inmobiliaria.git
cd inmobiliaria
```

Todos los comandos siguientes se corren desde esta carpeta (la raíz), salvo que se indique otra.

---

## Paso 4 · Crear el entorno de Python

Se crea una vez y se **activa cada vez** que abres una terminal nueva.

**Windows (PowerShell):**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Si PowerShell bloquea la activación, corre una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Mac / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

La terminal muestra `(.venv)` al inicio cuando el entorno está activo.

---

## Paso 5 · Configurar la base de datos

Crea tu archivo de configuración a partir del ejemplo:

```bash
cp .env.example .env        # Mac / Linux
copy .env.example .env      # Windows
```

El `.env` tiene claves: **nunca se sube a GitHub** (ya está en `.gitignore`).

### Opción A · Base local con Docker (recomendada para programar)

```bash
docker compose up -d
```

La primera vez carga automáticamente todos los archivos de `db/` (tablas, comunas y portales). El `DATABASE_URL` de `.env.example` ya apunta a esta base. Para empezar de cero: `docker compose down -v` y luego `docker compose up -d`.

### Opción B · Base en Neon (la compartida del equipo)

Neon es la base que usarán la API desplegada y la ejecución diaria. **Solo una persona la crea** y comparte la cadena de conexión por un canal privado.

1. Crea una cuenta en [neon.tech](https://neon.tech) y un proyecto `inmobiliaria` con PostgreSQL 16.
2. Copia la **Connection string** (termina en `?sslmode=require`) y pégala en tu `.env` como `DATABASE_URL=...`.
3. Crea las tablas:

   ```bash
   python scripts/init_db.py
   ```

### Actualizar una base que ya existe

Cuando se agregan datos iniciales nuevos (por ejemplo, el portal TocToc en `db/03_portales_extra.sql`), basta con volver a correr:

```bash
python scripts/init_db.py
```

Si la base ya tiene tablas, no borra nada: solo carga lo que falte. Para borrar todo y recrearla: `python scripts/init_db.py --reset` (pide confirmación).

---

## Paso 6 · Verificar que todo está listo

```bash
python scripts/check_setup.py
```

Debe terminar con:

```
[OK]    Tablas y datos iniciales: 12 tablas, 4 portales, 52 comunas

Todo listo para empezar a programar.
```

Y las pruebas deben pasar (no necesitan internet; las de la API se saltan si no hay base):

```bash
pytest
```

---

## Paso 7 · Correr los scrapers

### Chilepropiedades (Scrapy)

```bash
cd scrapers
scrapy crawl chilepropiedades -a max_paginas=2     # corrida corta, ~20 avisos
scrapy crawl chilepropiedades                      # corrida completa (marca bajas al final)
```

El spider lee primero los **datos estructurados JSON-LD** de cada ficha (precio, moneda, dormitorios, baños, superficies, gastos comunes, fecha). Solo si falta algo usa los rótulos del HTML. La descripción completa sale del contenedor `.clp-description-box`, porque la del JSON-LD viene recortada.

### TocToc (property_search)

Desde la raíz:

```bash
python scrapers/cargar_property_search.py --operation arriendo --type departamento --max-pages 2
```

Acepta los mismos argumentos que `scrapers/property_search/main.py` (`--commune`, `--bedrooms`, `--price`, `--currency`, `--url-only`, etc.), más `--marcar-bajas`, que sirve cuando la búsqueda cubre todo el portal. Ejemplos de filtros en el docstring de `property_search/main.py`.

`property_search/` se usa sin modificarlo. El adaptador solo convierte cada `Listing` al formato común y lo guarda con `core/guardado.py`:

| `Listing` (property_search) | `publicacion` (nuestra base) | Nota |
| --- | --- | --- |
| `listing_id`, `url`, `title`, `description` | `id_externo`, `url`, `titulo`, `descripcion` | La URL relativa se completa con el dominio |
| `price_clp`, `price_uf`, `price_currency` | `precio_clp`, `precio_uf`, `precio_monto` + `precio_moneda` | |
| `operation`, `property_type` | `operacion`, `tipo_propiedad` | Se pasan a minúscula |
| `bedrooms`, `bathrooms` (listas) | `dormitorios`, `banos` | En proyectos con varias tipologías se toma el menor |
| `area_m2` | `m2_util` | Igual que el filtro `superficie-util` de TocToc |
| `hours_published` | `fecha_publicacion` | Se calcula restando las horas a la fecha actual |
| `commune`, `lat`, `lon` | `comuna_id`, `latitud`, `longitud` | |
| `broker`, `flags` | — | No se guardan; los `flags` se muestran al final de la corrida |

**Descarga (decisión pendiente del equipo):** por ahora TocToc se descarga con el `fetch()` original de `property_search`, que usa `curl_cffi` con `impersonate="chrome"` (por eso `curl_cffi` está en `requirements.txt`). El adaptador trae una alternativa, `DescargaHonesta`: User-Agent del proyecto y respeto de robots.txt. Está desactivada con una línea comentada en `main()` (`# buscador.fetch = descarga`). Para activarla, descomenta esa línea. Antes del cierre de la Entrega 2, el equipo debe decidir cuál se usa y dejarlo registrado en el plan de riesgos, que hoy dice "rotación de proxies".

### Los dos a la vez y cómo revisar el resultado

Se pueden correr al mismo tiempo, en dos terminales: cada uno registra su propia ejecución.

```bash
python scripts/resumen.py
```

Ejemplo de salida:

```
portal             activos  última ejecución       sin error
chilepropiedades        20  #3 parcial            100.0% (20/20)
yapo                     0  nunca                          -
economicos               0  nunca                          -
toctoc                  48  #2 parcial            97.9% (47/48)

Últimos errores:
  [toctoc] validacion: 1 validation error for AvisoNormalizado precio_monto ...
```

- **parcial** = se limitaron las páginas, o hubo algún aviso con error. Es lo esperado en corridas cortas.
- **sin error** = la métrica del Acta: la meta es **≥ 95%**.
- Para ver el detalle, consulta en la base `SELECT * FROM error_scraping ORDER BY id DESC;`.

---

## Paso 8 · API y frontend

**API** (desde la raíz):

```bash
uvicorn api.main:app --reload
```

Documentación interactiva en [http://localhost:8000/docs](http://localhost:8000/docs).

**Frontend** (en otra terminal):

```bash
cd web
npm install
cp .env.example .env.local     # Windows: copy .env.example .env.local
npm run dev
```

Abre [http://localhost:5173](http://localhost:5173). Deben aparecer avisos de ambos portales, cada uno con su botón "Ver aviso original en …".

---

## Validaciones que protegen la base

Todo aviso pasa por `AvisoNormalizado` (`core/modelos.py`) antes de guardarse. Si falla, queda en `error_scraping` y baja el % sin error, en vez de llegar a la página:

- **Datos personales:** teléfonos, correos, RUT y nombres tras "Agente:" o "Contacto:" se reemplazan por `[telefono]`, `[correo]`, `[rut]` y `[nombre]`.
- **Precios imposibles:** arriendo entre $50.000 y $20 millones, o entre 1 y 500 UF; venta entre $5 millones y $50.000 millones, o entre 200 y 1.000.000 UF. Esto atrapa errores de lectura, como confundir pesos con UF.
- **Campos básicos:** URL válida, precio mayor que cero, dormitorios y baños entre 0 y 20, portal conocido.

Los números se leen a la chilena (`core/normalizacion.py`): `"$ 550.000"` → 550000, `"UF 13,35"` → 13.35, `"1.200 m²"` → 1200 y `"37.00 m²"` → 37. De un texto con varios precios se toma solo el **primero** con su propio símbolo, así la "UF de referencia" que muestran algunos portales no cambia la moneda.

---

## Cómo agregar un portal nuevo (Yapo, Economicos)

Primero revisa si la página trae **datos estructurados**: es más confiable leerlos que adivinar a partir del HTML. En el navegador, con "Ver código fuente", busca:
- `__NEXT_DATA__`, un JSON de sitios hechos con Next.js, como TocToc y Yapo;
- `application/ld+json`, el JSON-LD de schema.org, como Chilepropiedades.

Hay dos caminos, y los dos terminan en la misma base:

**A. Como clase de `property_search`** (lo más natural si las páginas de **listado** traen todos los datos, como con `__NEXT_DATA__`):
1. Crea `scrapers/property_search/search/sites/YapoSearch.py`, que herede de `PropertySearch` e implemente `build_url()` y `extract()` (ver `TocTocSearch.py`).
2. Regístrala en `SearchFactory._REGISTRY`.
3. Agrega el portal a `db/03_portales_extra.sql` si no está, y corre `python scripts/init_db.py`.
4. Prueba: `python scrapers/cargar_property_search.py --site yapo --operation arriendo --type departamento --max-pages 2`.

**B. Como spider de Scrapy** (lo más natural si hay que entrar a la **ficha** de cada aviso, como en Chilepropiedades):
1. Copia `spiders/chilepropiedades.py` como `spiders/yapo.py`, y cambia `name` (igual al `codigo` de la tabla `portal`) y `allowed_domains`.
2. Ajusta la URL del listado, la paginación y la lectura de la ficha. Devuelve un diccionario con los campos de `AvisoNormalizado`.
3. Prueba: `scrapy crawl yapo -a max_paginas=2`.

En los dos casos: guarda una página real en `tests/fixtures/` y escribe una prueba como las de `tests/test_chilepropiedades.py`.

### Guardar páginas para pruebas

Usa **"Guardar como → Página web, solo HTML"** del navegador. **No uses** `scrapy fetch ... > archivo.html` en PowerShell: la redirección con `>` cambia la codificación y daña los acentos ("cómodo" queda como "c├│modo").

---

## Cómo trabajamos en equipo

- **Nunca se trabaja directo en `main`.** Cada tarea va en su rama (`git checkout -b scraper-yapo`) y se integra con un Pull Request que otra persona revisa.
- El CI corre en cada Pull Request; si está en rojo, se arregla antes de integrar.
- **El contrato entre todos es `core/modelos.py`** (formato del aviso) **y `db/01_schema.sql`** (tablas). Si cambias uno, cambia el otro en el mismo Pull Request y avisa al equipo.
- `scrapers/property_search/` lo mantiene su autor. El estilo del CI (`ruff`) no lo revisa.
- Nunca subas el `.env`, claves ni cadenas de conexión.

**Reglas de datos acordadas** (revisión legal 2.1.3): solo páginas públicas y sin login; pausa de 2 segundos entre requests; no guardar nombre, teléfono, correo ni RUT del publicante; no republicar fotos ni descripciones completas en la web (solo un extracto y siempre el enlace al aviso original). La forma de descargar TocToc está pendiente (ver Paso 7).

---

## Despliegue (para la demo)

| Pieza | Dónde | Configuración |
| --- | --- | --- |
| Base | Neon | Paso 5, opción B |
| API | [Render](https://render.com) → New → Web Service desde el repositorio | Build: `pip install -r requirements.txt` · Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT` · Variables: `DATABASE_URL`, `CORS_ORIGINS` (la URL del frontend) |
| Frontend | [Vercel](https://vercel.com) o Netlify, desde el repositorio | Carpeta raíz: `web` · Variable: `VITE_API_URL` (la URL de Render) |

---

## Pendientes conocidos

- **Tercer portal:** Yapo (tiene `__NEXT_DATA__`) o Economicos.
- **Paginación de Chilepropiedades:** las fichas se verificaron contra una página real, pero el listado (`/0`, `/1`, …) todavía no. Hay que confirmarlo en la primera corrida real.
- **Superficie de TocToc en la web:** TocToc guarda `m2_util` y la tarjeta muestra solo `m2_total`. Para mostrarla, en `web/src/App.tsx` usa `a.m2_total ?? a.m2_util` y agrega `m2_util: string | null` al tipo `Aviso` en `web/src/api.ts`.
- **Decisión de descarga de TocToc** y su registro en el plan de riesgos (Paso 7).
- **Si alcanza:** detección de duplicados entre portales (`duplicado_de`) y ejecución diaria con GitHub Actions.

---

## Problemas comunes

| Síntoma | Solución |
| --- | --- |
| `[FALTA] Archivo .env con DATABASE_URL` | No copiaste `.env.example` a `.env`, o lo corres fuera de la raíz. |
| `connection refused` en `localhost:5432` | Docker no está corriendo: abre Docker Desktop y corre `docker compose up -d`. |
| El puerto 5432 está ocupado | En `docker-compose.yml` cambia `"5432:5432"` por `"5433:5432"` y en `.env` usa `localhost:5433`. |
| `El portal 'toctoc' no está en la tabla portal` | La base es anterior a TocToc: corre `python scripts/init_db.py`. |
| `ModuleNotFoundError: No module named 'core'` | Corre la API y el adaptador desde la raíz y Scrapy desde `scrapers/`, con el entorno activo. |
| TocToc: `Ejecución N (fallida)` con `HTTP 403` | El portal rechazó la descarga. Revisa `scripts/resumen.py` y conversa con el equipo antes de cambiar la forma de descargar. |
| Error `precio fuera de rango` | El precio se leyó mal (por ejemplo, pesos como UF) o el aviso tiene un precio absurdo. Revisa el aviso en `error_scraping`. |
| Scrapy dice `Forbidden by robots.txt` | Es lo correcto: esa URL no se puede visitar. No desactives `ROBOTSTXT_OBEY`. |
| Un campo sale siempre vacío | El sitio cambió su estructura: revisa con `scrapy shell "<url>"` y actualiza el fixture y la prueba. |
| Acentos dañados en un archivo `.html` guardado | Se guardó con `>` en PowerShell. Vuelve a guardarlo con el navegador. |
| El frontend dice "No se pudo cargar" | La API no está corriendo, o `VITE_API_URL` / `CORS_ORIGINS` no coinciden. |