"""Client for the public predictor behind red.cl's "Cuando llega" page.

m.ibus.cl drops every connection from Railway (measured 2026-11-17 in all four regions);
red.cl answers from Railway and carries the same arrival data.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from typing import Callable

import requests

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.red.cl/planifica-tu-viaje/cuando-llega/"
PREDICTOR_URL = "https://www.red.cl/predictorPlus/prediccion"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
}
# (connect, read). Measured from Railway us-east4: page ~1 s, predictor 1-1.6 s.
TIMEOUT_S = (3, 8)
# The page embeds a base64-wrapped JWT, valid ~60 min, that the predictor requires as ?t=.
JWT_PATTERN = re.compile(r"\$jwt\s*=\s*'([^']+)'")
TOKEN_REFRESH_MARGIN_S = 60
BUS_SLOTS = ("1", "2")


class RedClError(Exception):
    """Carries a fixed, client-safe message; the cause stays in the logs."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class RedClClient:
    def __init__(self, session: requests.Session | None = None, clock: Callable[[], float] = time.time) -> None:
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def query_stop(self, stop: str) -> dict:
        data = self._predict(stop, self._current_token())
        if data is None:
            # red.cl answers an expired or rejected token with a 500 text body; one retry with a fresh token.
            data = self._predict(stop, self._current_token(force_refresh=True))
        if data is None:
            raise RedClError("Respuesta inesperada de red.cl", 502)
        if not data.get("nomett"):
            raise RedClError("Paradero no encontrado en red.cl", 404)
        return to_stop_payload(data)

    def _predict(self, stop: str, token: str) -> dict | None:
        resp = self._get(PREDICTOR_URL, params={"t": token, "codsimt": stop, "codser": ""})
        try:
            data = resp.json()
        except ValueError:
            logger.warning("red.cl predictor returned %s non-JSON for %s", resp.status_code, stop)
            return None
        if resp.ok and isinstance(data, dict) and "nomett" in data:
            return data
        logger.warning("red.cl predictor returned %s with an unexpected body for %s", resp.status_code, stop)
        return None

    def _current_token(self, force_refresh: bool = False) -> str:
        # ponytail: one global lock, so an hourly refresh briefly queues concurrent requests; fine at this traffic.
        with self._token_lock:
            if force_refresh or self._token is None or self._clock() >= self._token_expires_at - TOKEN_REFRESH_MARGIN_S:
                self._token, self._token_expires_at = self._fetch_token()
            return self._token

    def _fetch_token(self) -> tuple[str, float]:
        resp = self._get(PAGE_URL)
        match = JWT_PATTERN.search(resp.text) if resp.ok else None
        if match is None:
            logger.warning("red.cl page returned %s without an embedded $jwt", resp.status_code)
            raise RedClError("Formato inesperado de red.cl", 502)
        try:
            token = base64.b64decode(match.group(1)).decode()
            claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            return token, float(claims["exp"])
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            logger.warning("red.cl $jwt could not be decoded: %s", type(exc).__name__)
            raise RedClError("Formato inesperado de red.cl", 502) from exc

    def _get(self, url: str, **kwargs) -> requests.Response:
        # Logs name the base URL and exception class only: the request URL carries the token.
        try:
            return self._session.get(url, timeout=TIMEOUT_S, **kwargs)
        except requests.Timeout as exc:
            logger.warning("red.cl timeout on %s: %s", url, type(exc).__name__)
            raise RedClError("red.cl no respondio a tiempo", 504) from exc
        except requests.RequestException as exc:
            logger.warning("red.cl request failed on %s: %s", url, type(exc).__name__)
            raise RedClError("No se pudo conectar con red.cl", 502) from exc


def to_stop_payload(data: dict) -> dict:
    servicios = data.get("servicios")
    items = servicios.get("item") if isinstance(servicios, dict) else None
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        logger.warning("red.cl prediction for %s has no servicios.item list", data.get("paradero"))
        raise RedClError("Formato inesperado de red.cl", 502)
    return {
        "paradero": data.get("paradero"),
        "nombre": data.get("nomett"),
        "hora_consulta": data.get("horaprediccion"),
        "servicios": [entry for item in items for entry in _service_entries(item)],
    }


def _service_entries(item: dict) -> list[dict]:
    slots = [n for n in BUS_SLOTS if item.get(f"ppubus{n}")]
    if not slots:
        return [{"servicio": item.get("servicio"), "bus": None, "tiempo": item.get("respuestaServicio"), "distancia_metros": None}]
    return [
        {
            "servicio": item.get("servicio"),
            "bus": item[f"ppubus{n}"],
            "tiempo": item.get(f"horaprediccionbus{n}"),
            "distancia_metros": _to_int(item.get(f"distanciabus{n}")),
        }
        for n in slots
    ]


def _to_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
