# SantiaGO — Explorador de Transporte Público

Aplicación web que muestra un mapa interactivo del transporte público de Santiago de Chile. Hacés clic en cualquier punto del mapa y el sistema te muestra la estación de metro más cercana y los 3 paraderos de bus más próximos, con tiempos de llegada en tiempo real.

**¿Qué podés hacer?**

- Clic en el mapa → marca la estación de metro más cercana y los 3 paraderos más próximos
- Hover sobre el mapa → líneas de conexión dinámicas al metro y buses cercanos
- Clic sobre un marcador → popup con datos en tiempo real (próximos buses, estado de la línea, horarios, accesibilidad)

---

## Cómo funciona

El proyecto tiene dos partes:

1. **Frontend** (`public/`) — HTML + CSS + JavaScript puro con Mapbox GL JS. Carga dos archivos GeoJSON estáticos (estaciones de metro y paraderos de bus) y los muestra en el mapa. Cuando hacés clic, calcula el punto más cercano con un índice espacial de grilla, y luego consulta al backend para obtener datos en tiempo real.

2. **Backend** (`api.py`) — API en FastAPI que hace scraping de `metro.cl` para obtener el estado de la red y los horarios de cada estación, y consulta `ibus-server.py` (un proxy separado) para los tiempos de llegada de buses. Los datos se cachean 5 minutos para no sobrecargar las fuentes externas.

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | HTML5 + CSS3 + JavaScript (vanilla) + Mapbox GL JS v2.15 |
| Backend | Python 3.11 + FastAPI 0.104 + Uvicorn / Gunicorn |
| Datos | GeoJSON (GTFS DTPM) + scraping Metro.cl + proxy iBUS |
| Deploy | Railway.app |

---

## Estructura del proyecto

```
santiaGO/
├── public/                                 ← frontend estático
│   ├── index.html
│   ├── css/main.css
│   ├── js/main.js                          (mapa, interactividad, llamadas a la API)
│   └── data/
│       ├── estaciones_with_lines.geojson   (~100 KB — estaciones con número de línea)
│       └── paraderos_santiago.geojson      (~3.7 MB — paraderos GTFS DTPM)
│
├── routes/                                 ← endpoints de la API
│   ├── health.py                           (GET /api/health)
│   ├── metro.py                            (GET /api/metro-network, /api/metro/estacion/...)
│   └── ibus.py                             (GET /api/paradero/{id})
│
├── metro/                                  ← módulo Python de datos de metro
│   ├── models.py                           (estructuras de datos: línea, estación, horarios)
│   ├── scraper.py                          (scraping de metro.cl)
│   ├── serializers.py                      (conversión modelos ↔ JSON)
│   ├── cache.py                            (caché en disco con TTL 5 min)
│   ├── cli.py                              (herramientas de línea de comando)
│   ├── services/
│   │   └── network_service.py             (singleton con caché en memoria de la red)
│   └── infrastructure/
│       └── ibus.py                         (cliente HTTP hacia el proxy iBUS)
│
├── api.py                                  ← aplicación FastAPI (punto de entrada)
├── ibus-server.py                          ← servidor proxy para m.ibus.cl
├── Procfile                                ← comando de inicio en producción
├── requirements.txt
├── runtime.txt                             ← Python 3.11
├── railway.toml                            ← configuración de deploy
└── .env.example                            ← variables de entorno de referencia
```

---

## Correr localmente

### Solo frontend (sin datos en tiempo real)

El frontend es HTML+CSS+JS puro, sin compilación ni Node.js.

**VS Code — Live Server:**
```
Clic derecho en public/index.html → "Open with Live Server"
```

**Servidor Python:**
```bash
cd public
python -m http.server 8080
# Abre http://localhost:8080
```

> No abras `index.html` directamente como `file://` — los fetch de los GeoJSON fallarán por CORS.

### Frontend + backend (datos en tiempo real)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Iniciar el servidor
uvicorn api:app --reload --host 0.0.0.0 --port 8000

# Abre http://localhost:8000
```

El backend también sirve el frontend estático desde `public/`, así que no necesitás levantar dos servidores.

---

## API endpoints

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado del servidor |
| `GET` | `/api/metro-network` | Estado de toda la red (caché 5 min) |
| `GET` | `/api/metro/estacion?nombre=<nombre>` | Detalle de estación por nombre |
| `GET` | `/api/metro/estacion/{codigo}` | Detalle de estación por código (ej: `BA`) |
| `GET` | `/api/paradero/{id}` | Próximos buses en un paradero (tiempo real) |
| `GET` | `/` | Frontend estático |

---

## Variables de entorno

Copiá `.env.example` a `.env` y completá los valores:

```env
# Token público de Mapbox (prefijo pk. — seguro para usarlo en el navegador)
MAPBOX_PUBLIC_TOKEN=pk.eyJ1...

# URL del proxy iBUS (usado por el backend en producción)
IBUS_PROXY_URL=https://...
```

---

## Deploy en Railway

```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

La app queda disponible en `https://santiago-production.up.railway.app` en ~2 minutos. Ver [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md) para la guía completa.

---

## Troubleshooting

**El mapa no carga / pantalla de carga infinita**

- Usá un servidor HTTP, no `file://`
- Verificá en la consola del navegador si hay errores de red

**Los GeoJSON devuelven 404**

- El servidor debe servir desde `public/` como raíz (no desde la raíz del proyecto)

**El popup no muestra datos en tiempo real**

- Verificá que el backend esté corriendo en el puerto 8000
- El primer request puede tardar más (caché fría); los siguientes son rápidos

---

## Fuentes de datos

| Fuente | Uso |
| --- | --- |
| [metro.cl](https://www.metro.cl) | Estado de la red, horarios, accesibilidad (scraping) |
| [m.ibus.cl](https://m.ibus.cl) | Tiempos de llegada de buses en tiempo real (proxy) |
| [DTPM — Ministerio de Transporte](https://www.dtpm.cl/index.php/gtfs-vigente) | Ubicación de paraderos (GTFS GeoJSON estático) |
| [Mapbox GL JS](https://docs.mapbox.com/mapbox-gl-js/) | Mapa base |
