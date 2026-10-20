# InmobiliarIA · Grupo 10

Plataforma web que reúne avisos de arriendo de varios portales chilenos y usa IA para encontrar lo que los filtros no capturan. Proyecto de Sextante Digital SpA para Aurora Propiedades (IIC3113).

Esta es la **base del repositorio**: estructura, base de datos, modelo de datos, pipeline de scraping, API y frontend mínimos, todo conectado y probado. Sobre ella se construyen los scrapers, la API y la interfaz.

---

## Qué hay en el repositorio

```
inmobiliaria/
├── core/                  Código compartido por scrapers y API
│   ├── config.py          Lee el archivo .env
│   ├── db.py              Conexión a PostgreSQL
│   ├── modelos.py         AvisoNormalizado: el formato común de un aviso (Pydantic)
│   ├── limpieza.py        Quita teléfonos, correos, RUT y nombres de las descripciones
│   ├── normalizacion.py   Precios, números y comunas al formato común
│   └── indicadores.py     Valor de la UF del día
├── db/
│   ├── 01_schema.sql      Las 12 tablas, vistas de métricas y portales
│   └── 02_comunas.sql     Las 52 comunas de la Región Metropolitana
├── scrapers/              Proyecto Scrapy
│   └── inmobiliaria_scrapers/
│       ├── settings.py    Reglas de cortesía: robots.txt, pausa de 2 s, User-Agent honesto
│       ├── pipelines.py   Valida, limpia, guarda y cuenta cada aviso
│       └── spiders/
│           ├── base.py              Clase base para todos los portales
│           └── chilepropiedades.py  Primer spider (selectores por verificar)
├── api/main.py            API FastAPI: /publicaciones, /comunas, /metricas, /health
├── web/                   Frontend React + TypeScript + Vite
├── scripts/
│   ├── init_db.py         Crea las tablas en la base del .env
│   └── check_setup.py     Verifica que todo esté listo
├── tests/                 Pruebas con pytest
├── docker-compose.yml     PostgreSQL 16 local
└── .github/workflows/ci.yml   Revisa cada push: estilo, pruebas y build
```

---

## Paso 1 · Instalar los programas (una vez por computador)

| Programa | Versión | Para qué | Cómo comprobar |
| --- | --- | --- | --- |
| [Git](https://git-scm.com/downloads) | cualquiera reciente | Control de versiones | `git --version` |
| [Python](https://www.python.org/downloads/) | 3.11 o más (recomendado 3.12) | Scrapers, API | `python --version` (Windows) o `python3 --version` (Mac/Linux) |
| [Node.js](https://nodejs.org/) | 22 LTS | Frontend | `node --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | opcional | Base de datos local | `docker --version` |

En Windows, al instalar Python marca la casilla **"Add python.exe to PATH"**.

Docker es opcional: si no lo instalas, trabajas directamente contra la base en Neon (Paso 5, opción B).

---

## Paso 2 · Crear el repositorio en GitHub (solo UNA persona del equipo)

1. Descomprime `inmobiliaria.zip` en tu carpeta de proyectos.
2. En [github.com/new](https://github.com/new) crea un repositorio **privado** llamado `inmobiliaria`, **sin** README ni `.gitignore` (ya vienen en esta base).
3. En una terminal, dentro de la carpeta `inmobiliaria`:

   ```bash
   git init
   git add .
   git commit -m "Base del proyecto: estructura, base de datos, pipeline, API y frontend"
   git branch -M main
   git remote add origin https://github.com/<usuario-u-organizacion>/inmobiliaria.git
   git push -u origin main
   ```

4. En GitHub: **Settings → Collaborators → Add people**, y agrega a los 5 integrantes.
5. Revisa la pestaña **Actions**: el CI debe aparecer en verde en unos minutos.

---

## Paso 3 · Clonar el repositorio (cada integrante)

```bash
git clone https://github.com/<usuario-u-organizacion>/inmobiliaria.git
cd inmobiliaria
```

Todos los comandos siguientes se corren desde esta carpeta (la raíz del repositorio), salvo que se indique otra.

---

## Paso 4 · Crear el entorno de Python

El entorno virtual (`.venv`) aísla las librerías del proyecto. Se crea una vez y se **activa cada vez** que abres una terminal nueva.

**Windows (PowerShell):**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Si PowerShell dice que la ejecución de scripts está deshabilitada, corre una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a activar.

**Mac / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

Sabes que el entorno está activo porque la terminal muestra `(.venv)` al inicio de la línea.

---

## Paso 5 · Configurar la base de datos

Primero crea tu archivo de configuración a partir del ejemplo:

```bash
cp .env.example .env        # Mac / Linux
copy .env.example .env      # Windows
```

El `.env` tiene claves: **nunca se sube a GitHub** (ya está en `.gitignore`).

### Opción A · Base local con Docker (recomendada para programar)

Cada integrante tiene su propia base y puede romperla sin afectar al resto.

```bash
docker compose up -d
```

La primera vez, el contenedor crea las tablas y carga portales y comunas automáticamente. El `DATABASE_URL` que viene en `.env.example` ya apunta a esta base: no hay que cambiar nada.

Para borrar todo y empezar de cero: `docker compose down -v` y luego `docker compose up -d`.

### Opción B · Base en Neon (la compartida del equipo)

Neon es la base que usarán la API desplegada y la ejecución diaria de los scrapers. **Solo una persona la crea**; al resto se le comparte la cadena de conexión por un canal privado (nunca en el repositorio).

1. Crea una cuenta en [neon.tech](https://neon.tech) (plan gratuito) y un proyecto llamado `inmobiliaria`, con PostgreSQL 16 y la región más cercana disponible.
2. En el panel, copia la **Connection string** (empieza con `postgresql://` y termina en `?sslmode=require`).
3. Pégala en tu `.env` como `DATABASE_URL=...` (y comenta la línea de Docker).
4. Crea las tablas:

   ```bash
   python scripts/init_db.py
   ```

   Si la base ya tiene tablas, el script no hace nada. Para borrar todo y recrearla: `python scripts/init_db.py --reset` (pide confirmación).

---

## Paso 6 · Verificar que todo está listo

```bash
python scripts/check_setup.py
```

Debe terminar así:

```
[OK]    Python: 3.12.x
[OK]    Paquetes instalados: scrapy, pydantic, psycopg, fastapi, python-dotenv
[OK]    Archivo .env con DATABASE_URL: localhost:5432/inmobiliaria
[OK]    Conexión a la base: PostgreSQL 16.x
[OK]    Tablas y datos iniciales: 12 tablas, 3 portales, 52 comunas

Todo listo para empezar a programar.
```

Y las pruebas deben pasar:

```bash
pytest
```

---

## Paso 7 · Levantar cada pieza

### Scrapers

```bash
cd scrapers
scrapy list                                   # debe mostrar: chilepropiedades
```

**Antes de la primera corrida real**, verifica los selectores del spider de Chilepropiedades contra el HTML real (se escribieron sin poder probarlos contra el sitio):

```bash
scrapy shell "https://chilepropiedades.cl/ver-publicacion/arriendo-mensual/nunoa/departamento/vicuna-mackenna-660/137904440"
```

Dentro del shell, prueba por ejemplo `response.xpath("//h1//text()").getall()` y ajusta `_valor()` o los XPath en `spiders/chilepropiedades.py` si algún campo sale vacío. Mientras ajustas, pon `HTTPCACHE_ENABLED = True` en `settings.py` para no descargar las mismas páginas una y otra vez.

Luego, una corrida corta de 2 páginas (~20 avisos):

```bash
scrapy crawl chilepropiedades -a max_paginas=2
```

Al final el log muestra un resumen como `Ejecución 1 (parcial): 20 leídos, 19 ok (95.0%)...`. También puedes revisarlo en la base:

```sql
SELECT * FROM v_tasa_exito_scraping ORDER BY inicio DESC;
SELECT tipo, url, mensaje FROM error_scraping ORDER BY id DESC LIMIT 20;
```

Una corrida **sin** `max_paginas` recorre todo el portal y, al terminar, marca como inactivos los avisos que ya no aparecen.

### API

Desde la raíz del repositorio:

```bash
uvicorn api.main:app --reload
```

Abre [http://localhost:8000/docs](http://localhost:8000/docs): ahí se pueden probar todos los endpoints.

### Frontend

En otra terminal:

```bash
cd web
npm install
cp .env.example .env.local     # Windows: copy .env.example .env.local
npm run dev
```

Abre [http://localhost:5173](http://localhost:5173). La página muestra los avisos que haya en la base, con filtros y el enlace al aviso original. Necesita la API corriendo.

---

## Cómo trabajamos en equipo

- **Nunca se trabaja directo en `main`.** Cada tarea va en su rama: `git checkout -b scraper-yapo`, y se integra con un Pull Request que otra persona revisa.
- El CI corre en cada Pull Request; si está en rojo, se arregla antes de integrar.
- Cada integrante trabaja principalmente en su carpeta: `scrapers/` y `core/` (backend e IA), `api/`, `web/` (frontend).
- **El contrato entre todos es `core/modelos.py`** (formato del aviso) **y `db/01_schema.sql`** (tablas). Si cambias uno, cambia el otro en el mismo Pull Request y avísale al equipo.
- Nunca subas el `.env`, claves ni cadenas de conexión.

## Cómo agregar un portal nuevo (Yapo, Economicos)

1. Copia `scrapers/inmobiliaria_scrapers/spiders/chilepropiedades.py` como `yapo.py`.
2. Cambia `name` (debe ser igual al `codigo` de la tabla `portal`: `yapo` o `economicos`) y `allowed_domains`.
3. Ajusta la URL del listado, cómo se pasa de página y cómo se lee la ficha. En Yapo, revisa primero si la página trae los datos en `<script id="__NEXT_DATA__">`: leer ese JSON es más fácil y estable que el HTML.
4. Devuelve un diccionario con los campos de `AvisoNormalizado`. El pipeline se encarga del resto: validar, limpiar datos personales, convertir precios, guardar y contar.
5. Prueba con `scrapy crawl yapo -a max_paginas=2`.

**Reglas que no se cambian** (revisión legal 2.1.3): respetar robots.txt, mantener la pausa de 2 segundos, no leer bloques de contacto y, si un portal bloquea, dejarlo: nunca usar proxies, resolver captchas ni camuflar el navegador.

## Despliegue (para la demo)

| Pieza | Dónde | Configuración |
| --- | --- | --- |
| Base | Neon | Paso 5, opción B |
| API | [Render](https://render.com) → New → Web Service desde el repositorio | Build: `pip install -r requirements.txt` · Start: `uvicorn api.main:app --host 0.0.0.0 --port $PORT` · Variables: `DATABASE_URL`, `CORS_ORIGINS` (la URL del frontend) |
| Frontend | [Vercel](https://vercel.com) o Netlify, desde el repositorio | Carpeta raíz: `web` · Variable: `VITE_API_URL` (la URL de Render) |

## Problemas comunes

| Síntoma | Solución |
| --- | --- |
| `[FALTA] Archivo .env con DATABASE_URL` | No copiaste `.env.example` a `.env`, o la corres fuera de la raíz del repositorio. |
| `connection refused` en `localhost:5432` | Docker no está corriendo: abre Docker Desktop y corre `docker compose up -d`. |
| El puerto 5432 está ocupado | Ya tienes otro PostgreSQL instalado. En `docker-compose.yml` cambia `"5432:5432"` por `"5433:5432"` y en `.env` usa `localhost:5433`. |
| `faltan [...]; corre python scripts/init_db.py` | La base existe pero está vacía. Corre el script. |
| `ModuleNotFoundError: No module named 'core'` | Corre la API desde la raíz y Scrapy desde `scrapers/`, con el entorno virtual activo. |
| Scrapy dice `Forbidden by robots.txt` | Es el comportamiento correcto: esa URL no se puede visitar. No desactives `ROBOTSTXT_OBEY`. |
| Un campo del aviso sale siempre vacío | El selector no calza con el HTML real: revísalo con `scrapy shell`. |
| El frontend dice "No se pudo cargar" | La API no está corriendo, o `VITE_API_URL` / `CORS_ORIGINS` no coinciden. |
