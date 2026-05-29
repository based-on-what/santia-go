"""
Simple JSON file cache for NetworkStatus.
Default TTL: 5 minutes (suitable for real-time status checks).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from typing import Optional

from .models import NetworkStatus
from .serializers import network_from_dict, network_to_dict

_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".metro_cache.json")
_DEFAULT_TTL = timedelta(minutes=5)


def save_cache(network: NetworkStatus, path: str = _CACHE_PATH) -> None:
    dir_ = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(network_to_dict(network), f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_cache(
    path: str = _CACHE_PATH,
    ttl: timedelta = _DEFAULT_TTL,
) -> Optional[tuple[NetworkStatus, timedelta]]:
    """
    Returns (NetworkStatus, age) if the cache exists and is within TTL.
    Returns None if missing, expired, or corrupted.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data["timestamp"])
        age = datetime.now() - cached_at
        if age > ttl:
            return None
        return network_from_dict(data), age
    except Exception:
        return None
