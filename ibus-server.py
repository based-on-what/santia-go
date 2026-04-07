import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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


def _consultar(paradero: str) -> str:
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(f"{BASE_URL}/index.jsp", verify=False, timeout=10)
    params = {
        "paradero": paradero,
        "servicio": "",
        "button": "Consulta Paradero",
    }
    resp = session.get(f"{BASE_URL}/Servlet", params=params, verify=False, timeout=10)
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
            # Fila completa: servicio, bus, tiempo, distancia
            ultimo_svc = celdas[0].text.strip()
            servicios.append({"servicio": ultimo_svc, "bus": celdas[1].text.strip(), "tiempo": celdas[2].text.strip(), "distancia": celdas[3].text.strip()})
        elif len(celdas) == 3:
            # Fila de continuación (rowspan): bus, tiempo, distancia — sin celda de servicio
            servicios.append({"servicio": ultimo_svc, "bus": celdas[0].text.strip(), "tiempo": celdas[1].text.strip(), "distancia": celdas[2].text.strip()})
        elif len(celdas) == 2:
            # Sin buses: servicio, mensaje
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
    try:
        html = _consultar(paradero)
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Timeout al contactar m.ibus.cl")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))
    return _parsear(html, paradero)


@app.get("/debug/{paradero}")
def debug_paradero(paradero: str):
    from fastapi.responses import HTMLResponse
    html = _consultar(paradero.upper().strip())
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
