# SantiaGO — Explorador de Transporte Público

Aplicación web para explorar el transporte público de Santiago de Chile en tiempo real. Muestra un mapa interactivo donde puedes encontrar la estación de metro más cercana y los 3 paraderos de bus más próximos a cualquier punto de la ciudad.

**Funcionalidades:**
- Clic en el mapa → marca la estación de metro más cercana y los 3 paraderos de bus más próximos
- Hover sobre el mapa → líneas de conexión en tiempo real al metro y paraderos cercanos
- Clic sobre un marcador → popup con datos en tiempo real (próximos buses, estado de la línea de metro)
- Leyenda visual con colores diferenciados por tipo de transporte

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | HTML5 + CSS3 + JavaScript (vanilla) + Mapbox GL JS v2.15 |
| Backend | Python 3.11 + FastAPI 0.104 + Uvicorn/Gunicorn |
| Datos | GeoJSON (GTFS DTPM) + scraping Metro.cl + iBUS proxy |
| Deploy | Railway.app |

---

## Estructura del proyecto

```
santiaGO/
├── public/                              ← frontend estático
│   ├── index.html
│   ├── css/main.css
│   ├── js/main.js                       (mapa, interactividad, llamadas a la API)
│   └── data/
│       ├── estaciones_with_lines.geojson   (~100 KB — estaciones de metro con línea)
│       └── paraderos_santiago.geojson      (~3.7 MB — paraderos GTFS DTPM)
│
├── metro/                               ← módulo Python de scraping
│   ├── models.py                        (modelos de datos)
│   ├── scraper.py                       (scraping de metro.cl)
│   ├── cache.py                         (caché en disco, TTL 5 min)
│   └── cli.py                           (herramientas de línea de comando)
│
├── api.py                               ← aplicación FastAPI (backend principal)
├── ibus-server.py                       ← servidor proxy para iBUS
├── Procfile                             ← comando de inicio en producción
├── requirements.txt                     ← dependencias Python
├── runtime.txt                          ← versión de Python (3.11)
├── pyproject.toml                       ← metadata del proyecto
├── railway.toml                         ← configuración de deploy en Railway
├── .env.example                         ← variables de entorno de referencia
├── RAILWAY_DEPLOYMENT.md                ← guía detallada de deploy
└── README.md
```

---

## Correr localmente

### Solo frontend

El frontend es HTML+CSS+JS puro — no requiere compilación ni Node.js.

**Opción A — Live Server (VS Code):**
```
Clic derecho en public/index.html → "Open with Live Server"
```

**Opción B — servidor Python:**
```bash
cd public
python -m http.server 8080
# Abre http://localhost:8080
```

**Opción C — npx serve:**
```bash
npx serve public
```

> No abras `public/index.html` directo como `file://` — los `fetch()` de los GeoJSON fallarán por CORS.

### Frontend + Backend (datos en tiempo real)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Iniciar el servidor API
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# El frontend ya estará disponible en http://localhost:8000
```

---

## API endpoints

El backend expone los siguientes endpoints:

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado del servidor |
| `GET` | `/api/paradero/{id}` | Tiempos en tiempo real para un paradero |
| `GET` | `/api/metro-network` | Estado de toda la red de metro |
| `GET` | `/api/metro/estacion?nombre=<nombre>` | Detalle de estación por nombre |
| `GET` | `/api/metro/estacion/{codigo}` | Detalle de estación por código |
| `GET` | `/` | Frontend (archivos estáticos desde `public/`) |

**Fuentes de datos en tiempo real:**
- Metro: scraping de `metro.cl` con caché de 5 minutos
- Buses: proxy hacia iBUS (`ibus-server.py`)

---

## Variables de entorno

Ver `.env.example` para el listado completo. Las principales son:

```env
# Token público de Mapbox (prefijo pk. — seguro para el navegador)
MAPBOX_PUBLIC_TOKEN=pk.eyJ1...

# URL del proxy iBUS (usado por el backend en producción)
IBUS_PROXY_URL=https://...

# URL de la API Red (alternativa al proxy iBUS)
RED_API_URL=https://red-proxy.TU_USUARIO.workers.dev
```

El token de Mapbox tiene prefijo `pk.` (*public key*) — está diseñado por Mapbox para usarse en el navegador y no es un secreto.

---

## Datos GeoJSON

Los archivos en `public/data/` son la fuente de datos estáticos de la app:

| Archivo | Tamaño | Contenido |
|---|---|---|
| `estaciones_with_lines.geojson` | ~100 KB | Estaciones de Metro con número de línea |
| `paraderos_santiago.geojson` | ~3.7 MB | Paraderos de bus (fuente: GTFS DTPM) |

No modificar estos archivos salvo que haya una actualización deliberada de datos.

---

## Deploy en Railway

El proyecto está configurado para desplegar en [Railway.app](https://railway.app) con un solo comando.

```bash
# Instalar CLI de Railway
npm install -g @railway/cli

# Login y deploy
railway login
railway init
railway up
```

La app estará disponible en ~2 minutos en una URL del tipo:
`https://santiago-production.up.railway.app`

Ver [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) para la guía completa con variables de entorno, dominios personalizados y monitoreo.

---

## Troubleshooting

**El mapa no carga / pantalla de carga infinita**
- Asegúrate de estar usando un servidor HTTP (no `file://`)
- Revisa la consola del navegador para errores de fetch o de red
- Confirma que los archivos `.geojson` existen en `public/data/`

**Los GeoJSON devuelven 404**
- Las rutas en `main.js` son relativas: `./data/estaciones_with_lines.geojson`
- El servidor debe estar sirviendo desde `public/` como raíz

**El popup no muestra datos en tiempo real**
- Verifica que el backend esté corriendo en el puerto 8000
- Revisa la consola del navegador por errores de CORS o de red
- El caché tiene TTL de 5 minutos; los primeros requests pueden ser más lentos

---

## Fuentes de datos

| Fuente | Enlace |
|---|---|
| GeoJSON GTFS buses | [DTPM — Ministerio de Transporte](https://www.dtpm.cl/index.php/gtfs-vigente) |
| Estado e info del metro | [metro.cl](https://www.metro.cl) (scraping) |
| Mapa base | [Mapbox GL JS](https://docs.mapbox.com/mapbox-gl-js/) |
