# api.py
import sys
import os
import re
import base64
import time

# Permite importar el paquete 'metro' desde el mismo directorio que api.py
sys.path.insert(0, os.path.dirname(__file__))

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(
    title="API local Red de Santiago",
    description="Paraderos red.cl + Metro de Santiago (desarrollo local)",
    version="3.0.0"
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

# ── red.cl ─────────────────────────────────────────────────────────────────────

_RED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CL,es;q=0.9",
    "Referer": "https://www.red.cl/planifica-tu-viaje/cuando-llega/",
}

# Caché: (timestamp, token, session)
_RED_SESSION_CACHE: tuple[float, str, requests.Session] | None = None
_RED_TOKEN_TTL = 1800  # 30 minutos


def _get_red_session() -> tuple[str, requests.Session]:
    """Devuelve (token, session) con cookies activas de red.cl. Cachea por 30 min."""
    global _RED_SESSION_CACHE
    now = time.time()
    if _RED_SESSION_CACHE and now - _RED_SESSION_CACHE[0] < _RED_TOKEN_TTL:
        return _RED_SESSION_CACHE[1], _RED_SESSION_CACHE[2]

    session = requests.Session()
    session.headers.update({
        "User-Agent": _RED_HEADERS["User-Agent"],
        "Accept-Language": _RED_HEADERS["Accept-Language"],
    })

    try:
        res = session.get(
            "https://www.red.cl/planifica-tu-viaje/cuando-llega/",
            timeout=15,
        )
        res.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Error al obtener token de red.cl: {e}")

    m = re.search(r"\$jwt\s*=\s*'([^']+)'", res.text)
    if not m:
        raise HTTPException(status_code=502, detail="Token JWT no encontrado en red.cl")

    try:
        token = base64.b64decode(m.group(1)).decode("utf-8")
    except Exception:
        token = m.group(1)

    _RED_SESSION_CACHE = (now, token, session)
    return token, session


def _consultar_paradero_red(paradero: str, servicio: str = "") -> dict:
    global _RED_SESSION_CACHE

    def _do_request(token: str, session: requests.Session):
        return session.get(
            "https://www.red.cl/predictor/prediccion",
            params={"t": token, "codsimt": paradero, "codser": servicio},
            headers=_RED_HEADERS,
            timeout=15,
        )

    try:
        token, session = _get_red_session()
        res = _do_request(token, session)
        if res.status_code in (401, 403, 500):
            # Sesión o token expirado: forzar renovación y reintentar
            _RED_SESSION_CACHE = None
            token, session = _get_red_session()
            res = _do_request(token, session)
        res.raise_for_status()
        data = res.json()
    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=502, detail="Timeout al consultar red.cl")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Error al consultar red.cl: {e}")

    hora_consulta = data.get("horaprediccion", "")
    items = data.get("servicios", {}).get("item", [])
    if isinstance(items, dict):
        items = [items]

    _MSG = {
        "9":  lambda item: item.get("respuestaServicio", "Servicio frecuente"),
        "10": lambda _: "Sin recorridos hacia este paradero",
        "11": lambda _: "Paradero fuera de horario de operación",
        "12": lambda _: "Servicio no disponible",
    }

    servicios = []
    for item in items:
        code = str(item.get("codigorespuesta", ""))
        svc = item.get("servicio", "")

        if code == "00":  # 2 buses en camino
            for n in ("1", "2"):
                dist = item.get(f"distanciabus{n}")
                servicios.append({
                    "servicio": svc,
                    "bus": item.get(f"ppubus{n}"),
                    "tiempo": item.get(f"horaprediccionbus{n}", ""),
                    "distancia_metros": int(dist) if dist else None,
                })
        elif code == "01":  # 1 bus en camino
            dist = item.get("distanciabus1")
            servicios.append({
                "servicio": svc,
                "bus": item.get("ppubus1"),
                "tiempo": item.get("horaprediccionbus1", ""),
                "distancia_metros": int(dist) if dist else None,
            })
        else:
            fn = _MSG.get(code, lambda i: i.get("respuestaServicio", "Sin información"))
            servicios.append({
                "servicio": svc,
                "bus": None,
                "tiempo": fn(item),
                "distancia_metros": None,
            })

    return {
        "paradero": paradero,
        "nombre": paradero,
        "hora_consulta": hora_consulta,
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


@app.get("/api/paradero/{paradero}", summary="Buses en tiempo real para un paradero (red.cl)")
@app.get("/paradero/{paradero}", include_in_schema=False)
def consultar_paradero(
    paradero: str,
    servicio: str = Query(default="", description="Filtrar por línea de bus (ej: 506)")
):
    """
    Consulta los próximos buses de un paradero vía red.cl.

    - **paradero**: código del paradero (ej: PA443)
    - **servicio**: opcional, filtra por línea
    """
    return _consultar_paradero_red(paradero.upper().strip(), servicio)


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
