# api.py
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

app = FastAPI(
    title="API Red de Santiago",
    description="Paraderos iBUS + Metro de Santiago",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_station_schedule_cache: dict[str, tuple[float, dict]] = {}
_SCHEDULE_TTL = 300

_IBUS_PROXY_URL = os.environ.get("IBUS_PROXY_URL", "").rstrip("/")


# ── iBUS vía proxy local (Cloudflare Tunnel) ──────────────────────────────────

def _consultar_paradero(paradero: str) -> dict:
    if not _IBUS_PROXY_URL:
        raise HTTPException(status_code=503, detail="IBUS_PROXY_URL no configurada.")
    try:
        res = requests.get(f"{_IBUS_PROXY_URL}/paradero/{paradero}", timeout=20)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout al consultar el proxy iBUS")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Error al consultar el proxy iBUS: {e}")


# ── Metro helpers ──────────────────────────────────────────────────────────────

def _get_network():
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
    from metro.scraper import fetch_station_schedule

    key = station.code.upper()
    now = time.time()

    if key in _station_schedule_cache:
        cached_at, _ = _station_schedule_cache[key]
        if now - cached_at < _SCHEDULE_TTL:
            return

    sched, term_a, term_b = fetch_station_schedule(station.code)
    station.schedule = sched
    station.terminal_a = term_a
    station.terminal_b = term_b
    _station_schedule_cache[key] = (now, {})


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {"mensaje": "API Red Santiago funcionando", "docs": "/docs"}


@app.get("/api/paradero/{paradero}", summary="Buses en tiempo real para un paradero (iBUS)")
@app.get("/paradero/{paradero}", include_in_schema=False)
def consultar_paradero(paradero: str):
    return _consultar_paradero(paradero.upper().strip())


@app.get("/api/metro-network", summary="Estado completo de la red de metro")
@app.get("/metro-network", include_in_schema=False)
def get_metro_network():
    from metro.cache import _network_to_dict
    return _network_to_dict(_get_network())


@app.get("/api/metro/estacion", summary="Detalle de una estación con horarios")
@app.get("/metro/estacion", include_in_schema=False)
def get_estacion(
    nombre: str = Query(..., description="Nombre exacto de la estación (ej: Baquedano)"),
):
    network = _get_network()
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

    _enrich_with_schedule(found_station)
    return _station_to_response(found_station, found_line_name)


@app.get("/api/metro/estacion/{code}", summary="Detalle de una estación por código")
@app.get("/metro/estacion/{code}", include_in_schema=False)
def get_estacion_by_code(code: str):
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


# ── Archivos estáticos ─────────────────────────────────────────────────────────

PUBLIC_DIR = Path(__file__).parent / "public"

if PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="static")
else:
    print(f"Advertencia: Carpeta public no encontrada en {PUBLIC_DIR}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
