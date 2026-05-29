import os
import threading
import time

import requests
import urllib3
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="iBUS Proxy local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

BASE_URL = "http://m.ibus.cl"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-CL,es-419;q=0.9,es;q=0.8",
    "Referer": f"{BASE_URL}/index.jsp",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

_CACHE_TTL = float(os.environ.get("IBUS_CACHE_TTL", "20"))

# Persistent session with connection pool — reused across all requests
_session = requests.Session()
_session.headers.update(HEADERS)
_adapter = HTTPAdapter(
    pool_connections=4,
    pool_maxsize=16,
    max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

# Warm up cookies once at startup
try:
    _session.get(f"{BASE_URL}/index.jsp", verify=False, timeout=10)
except Exception:
    pass

# In-memory response cache: stop_id -> (result_dict, timestamp)
_cache: dict[str, tuple[dict, float]] = {}
_cache_lock = threading.Lock()


def _consultar(paradero: str) -> str:
    params = {
        "paradero": paradero,
        "servicio": "",
        "button": "Consulta Paradero",
    }
    resp = _session.get(f"{BASE_URL}/Servlet", params=params, verify=False, timeout=10)
    resp.raise_for_status()
    return resp.text


def _parsear(html: str, paradero: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    datos = {}
    tabla_cab = soup.find("table", class_="cabecera4")
    if tabla_cab:
        for fila in tabla_cab.find_all("tr"):
            celdas = fila.find_all("td")
            if len(celdas) == 3:
                datos[celdas[0].text.strip()] = celdas[2].text.strip()

    servicios = []
    ultimo_svc = ""
    for fila in soup.find_all("tr"):
        celdas = fila.find_all("td", class_="menu_respuesta")
        if not celdas:
            continue
        if len(celdas) == 4:
            ultimo_svc = celdas[0].text.strip()
            servicios.append({"servicio": ultimo_svc, "bus": celdas[1].text.strip(), "tiempo": celdas[2].text.strip(), "distancia": celdas[3].text.strip()})
        elif len(celdas) == 3:
            servicios.append({"servicio": ultimo_svc, "bus": celdas[0].text.strip(), "tiempo": celdas[1].text.strip(), "distancia": celdas[2].text.strip()})
        elif len(celdas) == 2:
            ultimo_svc = celdas[0].text.strip()
            servicios.append({"servicio": ultimo_svc, "bus": None, "tiempo": celdas[1].text.strip(), "distancia": None})

    return {
        "paradero": paradero,
        "nombre": datos.get("Nombre", datos.get("Nombre Parada", paradero)),
        "comuna": datos.get("Comuna", ""),
        "servicios": servicios,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/paradero/{paradero}")
def consultar_paradero(paradero: str):
    paradero = paradero.upper().strip()
    now = time.monotonic()

    with _cache_lock:
        entry = _cache.get(paradero)
        if entry and now - entry[1] < _CACHE_TTL:
            return entry[0]

    try:
        html = _consultar(paradero)
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout al contactar m.ibus.cl")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))

    result = _parsear(html, paradero)
    with _cache_lock:
        _cache[paradero] = (result, now)
    return result


@app.get("/debug/{paradero}")
def debug_paradero(paradero: str):
    from fastapi.responses import HTMLResponse
    html = _consultar(paradero.upper().strip())
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
