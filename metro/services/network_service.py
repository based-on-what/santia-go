"""Thread-safe in-memory cache for NetworkStatus plus per-station schedule enrichment."""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

from ..cache import load_cache, save_cache
from ..models import NetworkStatus, Station
from ..scraper import fetch_network_status, fetch_station_schedule
from ..serializers import network_to_dict

_NETWORK_TTL = 300.0
_SCHEDULE_TTL = 300.0


class NetworkService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._network: Optional[NetworkStatus] = None
        self._network_at: float = 0.0
        # Serialized JSON bytes cache — keyed by _network_at epoch to auto-invalidate on refresh
        self._json_lock = threading.Lock()
        self._network_json: Optional[bytes] = None
        self._network_json_epoch: float = 0.0
        # Per-station locks — prevents global serialization on schedule fetches
        self._station_locks: dict[str, threading.Lock] = {}
        self._station_locks_lock = threading.Lock()
        self._schedule_fetched_at: dict[str, float] = {}

    def _get_station_lock(self, key: str) -> threading.Lock:
        with self._station_locks_lock:
            if key not in self._station_locks:
                self._station_locks[key] = threading.Lock()
            return self._station_locks[key]

    def get_network(self) -> NetworkStatus:
        now = time.time()
        if self._network is not None and now - self._network_at < _NETWORK_TTL:
            return self._network
        with self._lock:
            now = time.time()
            if self._network is not None and now - self._network_at < _NETWORK_TTL:
                return self._network
            result = load_cache()
            if result:
                network, _ = result
            else:
                network = fetch_network_status()
                if not network:
                    raise RuntimeError("No se pudo obtener la red de metro")
                save_cache(network)
            self._network = network
            self._network_at = now
            self._schedule_fetched_at.clear()
            return network

    def get_network_json(self) -> bytes:
        """Return serialized network JSON bytes, rebuilt only when the network refreshes."""
        if self._network_json is not None and self._network_json_epoch == self._network_at:
            return self._network_json
        with self._json_lock:
            if self._network_json is not None and self._network_json_epoch == self._network_at:
                return self._network_json
            network = self.get_network()
            payload = json.dumps(
                network_to_dict(network), ensure_ascii=False, separators=(",", ":")
            ).encode()
            self._network_json = payload
            self._network_json_epoch = self._network_at
            return payload

    def enrich_schedule(self, station: Station) -> None:
        key = station.code.upper()
        now = time.time()

        # Fast path: already enriched and fresh
        fetched_at = self._schedule_fetched_at.get(key)
        if fetched_at is not None and now - fetched_at < _SCHEDULE_TTL and station.schedule is not None:
            return

        lock = self._get_station_lock(key)
        with lock:
            # Re-check under per-station lock
            now = time.time()
            fetched_at = self._schedule_fetched_at.get(key)
            if fetched_at is not None and now - fetched_at < _SCHEDULE_TTL and station.schedule is not None:
                return
            try:
                sched, term_a, term_b = fetch_station_schedule(station.code)
                station.schedule = sched
                station.terminal_a = term_a
                station.terminal_b = term_b
                self._schedule_fetched_at[key] = time.time()
            except Exception:
                pass


# Module-level singleton — state lives for the lifetime of the process
network_service = NetworkService()
