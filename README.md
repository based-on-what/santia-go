# Explorador de Transporte — Santiago

Sitio web estático de una sola página que muestra un mapa interactivo del transporte público de Santiago de Chile.

**Funcionalidad:**
- Haz clic en el mapa → marca la estación de metro más cercana y los 3 paraderos de bus más próximos
- Hover sobre el mapa → líneas de conexión en tiempo real al metro y paraderos más cercanos
- Clic sobre un marcador → popup con datos en tiempo real (buses próximos, estado de estación metro)

---

## Estructura del proyecto

```
santiaGO/
├── public/                  ← todo lo que Netlify sirve
│   ├── index.html
│   ├── css/
│   │   └── main.css
│   ├── js/
│   │   └── main.js
│   └── data/
│       ├── estaciones_with_lines.geojson   (100 KB — estaciones de metro)
│       └── paraderos_santiago.geojson      (3.7 MB — paraderos de bus)
├── tools/
│   └── python/              ← utilidades de desarrollo (no parte del deploy)
│       ├── api.py
│       ├── ibus.py
│       ├── requirements.txt
│       ├── metro/
│       └── README.md
├── netlify.toml
├── .gitignore
├── .env.example
└── README.md
```

---

## Correr localmente

El sitio es HTML+CSS+JS puro. No necesita compilación ni Node.

**Opción A — extensión Live Server (VS Code):**
Clic derecho sobre `public/index.html` → "Open with Live Server"

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

> No abras `public/index.html` directamente como archivo (`file://`) porque los `fetch()` de los GeoJSON fallaran por CORS.

---

## Datos GeoJSON

Los archivos en `public/data/` son la fuente de datos de la aplicación:

| Archivo | Tamaño | Contenido |
|---|---|---|
| `estaciones_with_lines.geojson` | ~100 KB | Estaciones de Metro con línea |
| `paraderos_santiago.geojson` | ~3.7 MB | Paraderos de bus (GTFS DTPM) |

El JS los carga así:
```js
fetch('./data/estaciones_with_lines.geojson')
fetch('./data/paraderos_santiago.geojson')
```

**No modificar el contenido de estos archivos** salvo actualización deliberada de datos.

---

## APIs usadas en el frontend

| API | URL | Notas |
|---|---|---|
| Mapbox GL JS (tiles + rutas) | `api.mapbox.com` | Token público (`pk.`) |
| Estado metro en tiempo real | `localhost:8000/metro/estacion?nombre=...` | Servidor Python local ([santiago-red-api](https://github.com/based-on-what/santiago-red-api)) |
| Tiempos de bus en tiempo real | `localhost:8000/paradero/{id}` | Servidor Python local ([santiago-red-api](https://github.com/based-on-what/santiago-red-api)) |

---

## Variables de entorno

### Token Mapbox

El token en `public/js/main.js` tiene prefijo `pk.` (*public key*):  
está **diseñado por Mapbox para usarse en el navegador** — no es un secreto.

Sin embargo, para gestión centralizada puedes guardarlo en Netlify:

**Netlify → Site Settings → Environment variables:**

| Variable | Descripción | Ejemplo |
|---|---|---|
| `MAPBOX_PUBLIC_TOKEN` | Token público de Mapbox GL | `pk.eyJ1Ijo...` |

Ver `.env.example` para referencia.

---

## Deploy en Netlify

### Configuración mínima

El archivo `netlify.toml` ya está configurado:

```toml
[build]
  publish = "public"
```

### Pasos

1. Crea un nuevo site en [app.netlify.com](https://app.netlify.com)
2. Conecta el repositorio (o arrastra la carpeta `public/` a Netlify Drop)
3. **Publish directory**: `public`
4. **Build command**: (dejar vacío — no hay build)
5. Deploy

El sitio queda disponible inmediatamente.

### Variables de entorno en Netlify (opcional)

Si quieres gestionar el token desde Netlify:
- Site Settings → Environment variables → Add variable
- `MAPBOX_PUBLIC_TOKEN` = `pk.eyJ1Ijo...`

> Nota: Para que el token sea leído en el HTML estático necesitarías un paso de build (ej. `sed`) o usar Netlify Edge Functions. La configuración actual hardcodea el token en `main.js`, lo cual es aceptable para tokens públicos de Mapbox.

---

## Herramientas Python (desarrollo)

Ver [`tools/python/README.md`](tools/python/README.md) para documentación completa.

Estas herramientas son independientes del sitio web y no son requeridas para el deploy.

---

## Troubleshooting

**El mapa no carga / pantalla de carga infinita**
- ¿Estás abriendo con un servidor HTTP? (no `file://`)
- Verifica la consola del navegador para errores de fetch
- Confirma que los archivos `.geojson` están en `public/data/`

**Los GeoJSON devuelven 404**
- Las rutas en `main.js` son `./data/estaciones_with_lines.geojson` — relativas al `index.html`
- Confirma que Netlify tiene `publish = "public"` (no la raíz)

**Popup no muestra datos en tiempo real**
- La API `api.xor.cl` es externa y puede estar temporalmente caída
- Revisa la consola del navegador para errores de CORS o red

---

## Fuentes de datos

| Fuente | URL |
|---|---|
| GeoJSON GTFS buses | [DTPM — Ministerio de Transporte](https://www.dtpm.cl/index.php/gtfs-vigente) |
| API buses y metro | [based-on-what/santiago-red-api](https://github.com/based-on-what/santiago-red-api) |
| Mapa base | [Mapbox GL JS](https://docs.mapbox.com/mapbox-gl-js/) |
