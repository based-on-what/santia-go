# Herramientas Python — santiago-red-api

Estas herramientas son **utilitarios de desarrollo** y también el **backend para producción en Railway**.  
El sitio en `public/` se sirve junto con este API Python en Railway.

---

## Estructura

```
tools/python/
├── api.py            # Servidor REST (FastAPI) — scraping iBUS + Metro en tiempo real
├── ibus.py           # Script CLI standalone — consulta paraderos desde terminal
├── requirements.txt  # Dependencias Python
└── metro/
    ├── __init__.py   # Inicialización del paquete
    ├── models.py     # Clases de datos (Línea, Estación, Horario, etc.)
    ├── scraper.py    # Scraper de metro.cl y APIs oficiales
    ├── cache.py      # Caché en archivo JSON (.metro_cache.json, TTL: 5 min)
    └── cli.py        # CLI con Rich: status, list, station, search, refresh, export
```

---

## Instalación

```bash
cd tools/python
pip install -r requirements.txt
```

---

## api.py — Servidor REST (FastAPI)

Servidor que expone endpoints REST para consultar:
- Tiempos de llegada de buses (iBUS scraping)
- Estado de estaciones de metro en tiempo real

Se despliega automáticamente en Railway.

```bash
uvicorn api:app --reload
# Disponible en http://127.0.0.1:8000
# Swagger UI en   http://127.0.0.1:8000/docs
```

**Endpoint:**
```
GET /paradero/{paradero}?servicio=506
```

---

## ibus.py — CLI standalone (sin servidor)

Misma funcionalidad que `api.py` pero para uso interactivo en terminal.

```bash
python ibus.py
# Pedirá el código del paradero (ej: PA443)
# Devuelve JSON con buses en tiempo real
```

---

## metro/ — CLI con Rich

Herramienta de terminal para consultar el estado de la red de Metro de Santiago.

```bash
python -m metro.cli status              # Estado general de la red
python -m metro.cli list --line L1      # Estaciones de la L1
python -m metro.cli station BA          # Detalle de estación Baquedano
python -m metro.cli station BA --full   # Con accesos y servicios
python -m metro.cli search baquedano    # Buscar estación por nombre
python -m metro.cli refresh             # Forzar actualización de caché
python -m metro.cli export -o data.json # Exportar todo a JSON
```

---

## Nota sobre secretos

Ninguno de estos scripts requiere tokens privados para funcionar.  
El scraping se realiza sobre URLs públicas (`metro.cl`, `m.ibus.cl`).
