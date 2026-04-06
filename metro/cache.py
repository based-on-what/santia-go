"""
Simple JSON file cache for NetworkStatus.
Default TTL: 5 minutes (suitable for real-time status checks).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Optional

from .models import (
    AccessPoint,
    DaySchedule,
    Line,
    NetworkStatus,
    Station,
    StationSchedule,
    TrainTimes,
)

_CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".metro_cache.json")
_DEFAULT_TTL = timedelta(minutes=5)


# ── Serialisation ──────────────────────────────────────────────────────────────

def _day_to_dict(d: DaySchedule) -> dict:
    return {"weekdays": d.weekdays, "saturday": d.saturday, "holidays": d.holidays}


def _schedule_to_dict(s: Optional[StationSchedule]) -> Optional[dict]:
    if s is None:
        return None
    return {"open": _day_to_dict(s.open), "close": _day_to_dict(s.close)}


def _train_to_dict(t: Optional[TrainTimes]) -> Optional[dict]:
    if t is None:
        return None
    return {
        "name": t.name,
        "first_train": _day_to_dict(t.first_train),
        "last_train": _day_to_dict(t.last_train),
    }


def _station_to_dict(s: Station) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "line_id": s.line_id,
        "enabled": s.enabled,
        "status_description": s.status_description,
        "message": s.message,
        "transfers": s.transfers,
        "schedule": _schedule_to_dict(s.schedule),
        "terminal_a": _train_to_dict(s.terminal_a),
        "terminal_b": _train_to_dict(s.terminal_b),
        "accesses": [{"name": a.name, "operational": a.operational} for a in s.accesses],
        "services": s.services,
    }


def _network_to_dict(n: NetworkStatus) -> dict:
    return {
        "timestamp": n.timestamp,
        "has_issues": n.has_issues,
        "lines": [
            {
                "id": line.id,
                "name": line.name,
                "operational": line.operational,
                "message": line.message,
                "stations": [_station_to_dict(s) for s in line.stations],
            }
            for line in n.lines
        ],
    }


# ── Deserialisation ────────────────────────────────────────────────────────────

def _day_from_dict(d: dict) -> DaySchedule:
    return DaySchedule(
        weekdays=d["weekdays"],
        saturday=d["saturday"],
        holidays=d["holidays"],
    )


def _schedule_from_dict(d: Optional[dict]) -> Optional[StationSchedule]:
    if d is None:
        return None
    return StationSchedule(
        open=_day_from_dict(d["open"]),
        close=_day_from_dict(d["close"]),
    )


def _train_from_dict(d: Optional[dict]) -> Optional[TrainTimes]:
    if d is None:
        return None
    return TrainTimes(
        name=d["name"],
        first_train=_day_from_dict(d["first_train"]),
        last_train=_day_from_dict(d["last_train"]),
    )


def _station_from_dict(d: dict) -> Station:
    return Station(
        code=d["code"],
        name=d["name"],
        line_id=d["line_id"],
        enabled=d["enabled"],
        status_description=d["status_description"],
        message=d["message"],
        transfers=d.get("transfers", []),
        schedule=_schedule_from_dict(d.get("schedule")),
        terminal_a=_train_from_dict(d.get("terminal_a")),
        terminal_b=_train_from_dict(d.get("terminal_b")),
        accesses=[AccessPoint(**a) for a in d.get("accesses", [])],
        services=d.get("services", {}),
    )


def _network_from_dict(d: dict) -> NetworkStatus:
    return NetworkStatus(
        timestamp=d["timestamp"],
        has_issues=d["has_issues"],
        lines=[
            Line(
                id=line["id"],
                name=line["name"],
                operational=line["operational"],
                message=line["message"],
                stations=[_station_from_dict(s) for s in line["stations"]],
            )
            for line in d["lines"]
        ],
    )


# ── Public API ─────────────────────────────────────────────────────────────────

def save_cache(network: NetworkStatus, path: str = _CACHE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_network_to_dict(network), f, ensure_ascii=False, indent=2)


def load_cache(
    path: str = _CACHE_PATH,
    ttl: timedelta = _DEFAULT_TTL,
) -> Optional[NetworkStatus]:
    """
    Returns a cached NetworkStatus if the cache exists and is within TTL.
    Returns None if missing, expired, or corrupted.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data["timestamp"])
        if datetime.now() - cached_at > ttl:
            return None
        return _network_from_dict(data)
    except Exception:
        return None


def cache_age(path: str = _CACHE_PATH) -> Optional[timedelta]:
    """Returns how old the cache is, or None if no cache exists."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data["timestamp"])
        return datetime.now() - cached_at
    except Exception:
        return None
