import sys
import requests
from bs4 import BeautifulSoup
import json

BASE_URL = "http://m.ibus.cl"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/29.0 Chrome/136.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-US,es-419;q=0.9,es;q=0.8",
    "Referer": f"{BASE_URL}/index.jsp",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

def consultar_paradero(paradero: str, servicio: str = ""):
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(f"{BASE_URL}/index.jsp", verify=False)

    params = {
        "paradero": paradero,
        "servicio": servicio,
        "button": "Consulta Paradero"
    }
    response = session.get(f"{BASE_URL}/Servlet", params=params, verify=False)
    return response.text

def parsear_resultado(html: str):
    soup = BeautifulSoup(html, "html.parser")

    # Cabecera
    tabla_cab = soup.find("table", class_="cabecera4")
    filas_cab = tabla_cab.find_all("tr") if tabla_cab else []
    datos = {}
    for fila in filas_cab:
        celdas = fila.find_all("td")
        if len(celdas) == 3:
            clave = celdas[0].text.strip()
            valor = celdas[2].text.strip()
            datos[clave] = valor

    # Servicios
    servicios = []
    for fila in soup.find_all("tr"):
        celdas = fila.find_all("td", class_="menu_respuesta")
        if not celdas:
            continue
        servicio = celdas[0].text.strip()
        if len(celdas) == 2:
            servicios.append({
                "servicio": servicio,
                "bus": None,
                "tiempo": celdas[1].text.strip(),
                "distancia": None
            })
        elif len(celdas) == 4:
            servicios.append({
                "servicio": servicio,
                "bus": celdas[1].text.strip(),
                "tiempo": celdas[2].text.strip(),
                "distancia": celdas[3].text.strip()
            })

    resultado = {**datos, "servicios": servicios}
    return resultado

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    paradero = input("Ingresa paradero (ej: PA443): ").strip().upper()
    html = consultar_paradero(paradero)
    resultado = parsear_resultado(html)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))