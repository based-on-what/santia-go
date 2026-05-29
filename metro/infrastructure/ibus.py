"""iBUS proxy client — no FastAPI dependencies."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class IBusProxyError(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _make_session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=8,
        pool_maxsize=64,
        max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
    )
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


class IBusClient:
    def __init__(self, proxy_url: str) -> None:
        self._url = proxy_url.rstrip("/")
        self._session = _make_session()

    def query_stop(self, stop: str) -> dict:
        if not self._url:
            raise IBusProxyError("IBUS_PROXY_URL no configurada.", 503)
        try:
            res = self._session.get(f"{self._url}/paradero/{stop}", timeout=20)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.Timeout:
            raise IBusProxyError("Timeout al consultar el proxy iBUS", 504)
        except requests.exceptions.RequestException as e:
            raise IBusProxyError(f"Error al consultar el proxy iBUS: {e}", 502)
