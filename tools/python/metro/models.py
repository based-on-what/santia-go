from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DaySchedule:
    weekdays: str   # lunes_viernes — e.g. "06:00" or "-"
    saturday: str   # sabado
    holidays: str   # domingo / festivos


@dataclass
class StationSchedule:
    open: DaySchedule
    close: DaySchedule


@dataclass
class TrainTimes:
    """First/last train times toward one terminal end of the line."""
    name: str
    first_train: DaySchedule
    last_train: DaySchedule


@dataclass
class AccessPoint:
    name: str
    operational: bool


@dataclass
class Station:
    code: str
    name: str
    line_id: str                            # e.g. "L1"
    enabled: bool
    status_description: str                 # e.g. "Estación Operativa"
    message: str                            # alert text, empty if none
    transfers: list[str] = field(default_factory=list)   # e.g. ["L5"]
    schedule: Optional[StationSchedule] = None
    terminal_a: Optional[TrainTimes] = None
    terminal_b: Optional[TrainTimes] = None
    accesses: list[AccessPoint] = field(default_factory=list)
    services: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Line:
    id: str         # e.g. "L1"
    name: str       # e.g. "Línea 1"
    operational: bool
    message: str
    stations: list[Station] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return not self.operational or any(not s.enabled for s in self.stations)

    @property
    def disabled_stations(self) -> list[Station]:
        return [s for s in self.stations if not s.enabled]


@dataclass
class NetworkStatus:
    timestamp: str
    lines: list[Line]
    has_issues: bool

    def get_station(self, code: str) -> Optional[Station]:
        code = code.upper()
        for line in self.lines:
            for station in line.stations:
                if station.code == code:
                    return station
        return None

    def get_line(self, line_id: str) -> Optional[Line]:
        line_id = line_id.upper()
        for line in self.lines:
            if line.id == line_id:
                return line
        return None

    def search(self, query: str) -> list[tuple[Line, Station]]:
        q = query.lower()
        results = []
        for line in self.lines:
            for station in line.stations:
                if q in station.name.lower() or q == station.code.lower():
                    results.append((line, station))
        return results
