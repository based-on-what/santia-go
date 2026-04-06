# api.py
import sys
import os
import time

# Permite importar el paquete 'metro' desde el mismo directorio que api.py
sys.path.insert(0, os.path.dirname(__file__))

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(
    title="API local Red de Santiago",
    description="Paraderos iBUS + Metro de Santiago (desarrollo local)",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Caché en memoria para horarios de estaciones (TTL: 5 min) ─────────────────
# { codigo_estacion: (timestamp_float, dict_resultado) }
_station_schedule_cache: dict[str, tuple[float, dict]] = {}
_SCHEDULE_TTL = 300  # segundos

# ── iBUS ───────────────────────────────────────────────────────────────────────

_IBUS_BASE_URL = os.environ.get("IBUS_PROXY_URL", "http://m.ibus.cl")
_IBUS_USE_PROXY = "IBUS_PROXY_URL" in os.environ
_IBUS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8,en-US;q=0.7,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Connection": "keep-alive",
}


def _scrape_paradero(paradero: str, servicio: str = "") -> dict:
    import time
    import random

    session = requests.Session()
    session.headers.update(_IBUS_HEADERS)

    # Cuando se usa proxy (Cloudflare Worker) no hace falta calentar sesión.
    # Directo al Servlet con timeout reducido para fallar rápido.
    if not _IBUS_USE_PROXY:
        try:
            session.get(f"{_IBUS_BASE_URL}/index.jsp", verify=False, timeout=8)
            time.sleep(random.uniform(0.5, 1.5))
        except requests.exceptions.RequestException:
            pass

    session.headers.update({
        "Referer": f"{_IBUS_BASE_URL}/index.jsp",
        "Origin": _IBUS_BASE_URL,
        "Content-Type": "application/x-www-form-urlencoded",
    })

    params = {"paradero": paradero, "servicio": servicio, "button": "Consulta Paradero"}
    timeout = 10 if _IBUS_USE_PROXY else 20

    try:
        response = session.get(f"{_IBUS_BASE_URL}/Servlet", params=params, verify=False, timeout=timeout)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        raise HTTPException(status_code=502, detail=f"Timeout al consultar paradero: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Error al consultar paradero en iBUS: {str(e)}")

    if response.status_code != 200 or len(response.text) < 100:
        raise HTTPException(status_code=502, detail="Error al obtener datos de iBUS")

    soup = BeautifulSoup(response.text, "html.parser")

    datos = {}
    tabla_cab = soup.find("table", class_="cabecera4")
    if tabla_cab:
        for fila in tabla_cab.find_all("tr"):
            celdas = fila.find_all("td")
            if len(celdas) == 3:
                datos[celdas[0].text.strip()] = celdas[2].text.strip().replace("\n", " ").strip()

    servicios = []
    for fila in soup.find_all("tr"):
        celdas = fila.find_all("td", class_="menu_respuesta")
        if not celdas:
            continue
        nombre_svc = celdas[0].text.strip()
        if len(celdas) == 2:
            servicios.append({"servicio": nombre_svc, "bus": None, "tiempo": celdas[1].text.strip(), "distancia_metros": None})
        elif len(celdas) == 4:
            dist = celdas[3].text.strip()
            servicios.append({
                "servicio": nombre_svc,
                "bus": celdas[1].text.strip(),
                "tiempo": celdas[2].text.strip(),
                "distancia_metros": int(dist) if dist.isdigit() else None
            })

    return {
        "paradero": datos.get("Paradero", paradero).strip(),
        "nombre": datos.get("Nombre", "").strip(),
        "hora_consulta": datos.get("Hora", "").strip(),
        "servicios": servicios,
    }


# ── Metro helpers ──────────────────────────────────────────────────────────────

def _get_network():
    """Devuelve NetworkStatus desde caché de archivo o scraping fresco."""
    from metro.cache import load_cache, save_cache
    from metro.scraper import fetch_network_status

    network = load_cache()
    if not network:
        network = fetch_network_status()
        if not network:
            raise HTTPException(status_code=502, detail="No se pudo obtener la red de metro")
        save_cache(network)
    return network


def _station_to_response(station, line_name: str) -> dict:
    """Serializa una Station a dict apto para JSON."""
    from metro.cache import _schedule_to_dict, _train_to_dict
    return {
        "code": station.code,
        "name": station.name,
        "line_id": station.line_id,
        "line_name": line_name,
        "enabled": station.enabled,
        "status_description": station.status_description,
        "message": station.message,
        "transfers": station.transfers,
        "schedule": _schedule_to_dict(station.schedule),
        "terminal_a": _train_to_dict(station.terminal_a),
        "terminal_b": _train_to_dict(station.terminal_b),
    }


def _enrich_with_schedule(station) -> None:
    """Agrega horarios a la estación; usa caché en memoria."""
    from metro.scraper import fetch_station_schedule

    key = station.code.upper()
    now = time.time()

    if key in _station_schedule_cache:
        cached_at, _ = _station_schedule_cache[key]
        if now - cached_at < _SCHEDULE_TTL:
            # Ya cacheado y fresco — solo recuperar los objetos
            sched_cached = _station_schedule_cache[key][1]
            # El objeto station ya tendrá el schedule si fue enriquecido antes;
            # si no, lo reconstruimos en el endpoint desde el dict cacheado.
            return

    sched, term_a, term_b = fetch_station_schedule(station.code)
    station.schedule = sched
    station.terminal_a = term_a
    station.terminal_b = term_b
    # Guardar marca de tiempo (el dict completo se arma en el endpoint)
    _station_schedule_cache[key] = (now, {})


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {"mensaje": "API local Red Santiago funcionando", "docs": "/docs"}


@app.get("/api/paradero/{paradero}", summary="Buses en tiempo real para un paradero (iBUS)")
@app.get("/paradero/{paradero}", include_in_schema=False)
def consultar_paradero(
    paradero: str,
    servicio: str = Query(default="", description="Filtrar por línea de bus (ej: 506)")
):
    """
    Scraping de m.ibus.cl para obtener los próximos buses de un paradero.

    - **paradero**: código del paradero (ej: PA443)
    - **servicio**: opcional, filtra por línea
    """
    return _scrape_paradero(paradero.upper().strip(), servicio)


@app.get("/api/metro-network", summary="Estado completo de la red de metro (con prefijo /api)")
@app.get("/metro-network", include_in_schema=False)
def get_metro_network():
    """
    Estado operacional de todas las líneas y estaciones (sin horarios).
    Caché en archivo, TTL 5 minutos.
    """
    from metro.cache import _network_to_dict
    return _network_to_dict(_get_network())


@app.get("/api/metro/estacion", summary="Detalle de una estación con horarios")
@app.get("/metro/estacion", include_in_schema=False)
def get_estacion(
    nombre: str = Query(..., description="Nombre exacto de la estación (ej: Baquedano)"),
):
    """
    Devuelve estado + horarios de apertura/cierre + trenes de una estación.

    - **nombre**: nombre exacto como aparece en el GeoJSON (ej: `Baquedano`, `U. de Chile`)

    Combina `/api/estadoRedDetalle.php` + `/api/horariosEstacion.php`.
    Los horarios se cachean en memoria por 5 minutos.
    """
    network = _get_network()

    # Buscar estación por nombre (insensible a mayúsculas)
    nombre_lower = nombre.strip().lower()
    found_station = None
    found_line_name = ""
    for line in network.lines:
        for station in line.stations:
            if station.name.lower() == nombre_lower:
                found_station = station
                found_line_name = line.name
                break
        if found_station:
            break

    if not found_station:
        raise HTTPException(status_code=404, detail=f"Estación '{nombre}' no encontrada en la red")

    # Enriquecer con horarios (con caché en memoria)
    _enrich_with_schedule(found_station)

    return _station_to_response(found_station, found_line_name)


@app.get("/api/metro/estacion/{code}", summary="Detalle de una estación por código")
@app.get("/metro/estacion/{code}", include_in_schema=False)
def get_estacion_by_code(code: str):
    """
    Devuelve estado + horarios de una estación por su código (ej: `BA` para Baquedano).
    """
    network = _get_network()

    code_upper = code.upper().strip()
    found_station = None
    found_line_name = ""
    for line in network.lines:
        for station in line.stations:
            if station.code.upper() == code_upper:
                found_station = station
                found_line_name = line.name
                break
        if found_station:
            break

    if not found_station:
        raise HTTPException(status_code=404, detail=f"Estación con código '{code}' no encontrada")

    _enrich_with_schedule(found_station)
    return _station_to_response(found_station, found_line_name)


# ── Servir archivos estáticos del frontend ──────────────────────────────────────

# Ruta a la carpeta public donde están los archivos estáticos
# En Railway: /app/public
# En local: ./public (relativo a la raíz del proyecto)
PUBLIC_DIR = Path(__file__).parent / "public"

if PUBLIC_DIR.exists():
    # Montar la carpeta public como static files
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
else:
    print(f"⚠️  Advertencia: Carpeta public no encontrada en {PUBLIC_DIR}")
    print("    El frontend no estará disponible")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
