from __future__ import annotations

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


# ── To-dict ───────────────────────────────────────────────────────────────────

def day_to_dict(d: DaySchedule) -> dict:
    return {"weekdays": d.weekdays, "saturday": d.saturday, "holidays": d.holidays}


def schedule_to_dict(s: Optional[StationSchedule]) -> Optional[dict]:
    if s is None:
        return None
    return {"open": day_to_dict(s.open), "close": day_to_dict(s.close)}


def train_to_dict(t: Optional[TrainTimes]) -> Optional[dict]:
    if t is None:
        return None
    return {
        "name": t.name,
        "first_train": day_to_dict(t.first_train),
        "last_train": day_to_dict(t.last_train),
    }


def station_to_api_dict(s: Station, line_name: str) -> dict:
    """API response shape: includes line_name, excludes accesses/services."""
    return {
        "code": s.code,
        "name": s.name,
        "line_id": s.line_id,
        "line_name": line_name,
        "enabled": s.enabled,
        "status_description": s.status_description,
        "message": s.message,
        "transfers": s.transfers,
        "schedule": schedule_to_dict(s.schedule),
        "terminal_a": train_to_dict(s.terminal_a),
        "terminal_b": train_to_dict(s.terminal_b),
    }


def station_to_dict(s: Station) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "line_id": s.line_id,
        "enabled": s.enabled,
        "status_description": s.status_description,
        "message": s.message,
        "transfers": s.transfers,
        "schedule": schedule_to_dict(s.schedule),
        "terminal_a": train_to_dict(s.terminal_a),
        "terminal_b": train_to_dict(s.terminal_b),
        "accesses": [{"name": a.name, "operational": a.operational} for a in s.accesses],
        "services": s.services,
    }


def network_to_dict(n: NetworkStatus) -> dict:
    return {
        "timestamp": n.timestamp,
        "has_issues": n.has_issues,
        "lines": [
            {
                "id": line.id,
                "name": line.name,
                "operational": line.operational,
                "message": line.message,
                "stations": [station_to_dict(s) for s in line.stations],
            }
            for line in n.lines
        ],
    }


# ── From-dict ─────────────────────────────────────────────────────────────────

def day_from_dict(d: dict) -> DaySchedule:
    return DaySchedule(
        weekdays=d["weekdays"],
        saturday=d["saturday"],
        holidays=d["holidays"],
    )


def schedule_from_dict(d: Optional[dict]) -> Optional[StationSchedule]:
    if d is None:
        return None
    return StationSchedule(
        open=day_from_dict(d["open"]),
        close=day_from_dict(d["close"]),
    )


def train_from_dict(d: Optional[dict]) -> Optional[TrainTimes]:
    if d is None:
        return None
    return TrainTimes(
        name=d["name"],
        first_train=day_from_dict(d["first_train"]),
        last_train=day_from_dict(d["last_train"]),
    )


def station_from_dict(d: dict) -> Station:
    return Station(
        code=d["code"],
        name=d["name"],
        line_id=d["line_id"],
        enabled=d["enabled"],
        status_description=d["status_description"],
        message=d["message"],
        transfers=d.get("transfers", []),
        schedule=schedule_from_dict(d.get("schedule")),
        terminal_a=train_from_dict(d.get("terminal_a")),
        terminal_b=train_from_dict(d.get("terminal_b")),
        accesses=[AccessPoint(**a) for a in d.get("accesses", [])],
        services=d.get("services", {}),
    )


def network_from_dict(d: dict) -> NetworkStatus:
    return NetworkStatus(
        timestamp=d["timestamp"],
        has_issues=d["has_issues"],
        lines=[
            Line(
                id=line["id"],
                name=line["name"],
                operational=line["operational"],
                message=line["message"],
                stations=[station_from_dict(s) for s in line["stations"]],
            )
            for line in d["lines"]
        ],
    )
