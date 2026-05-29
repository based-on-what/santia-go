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

    def __post_init__(self) -> None:
        # O(1) indices built once on construction
        self._by_code: dict[str, tuple[Station, Line]] = {}
        self._by_name: dict[str, tuple[Station, Line]] = {}
        self._by_line_id: dict[str, Line] = {}
        # Pre-lowercased list for O(n) substring search without per-call .lower()
        self._names_lower: list[tuple[str, str, "Station", "Line"]] = []
        for line in self.lines:
            self._by_line_id[line.id] = line
            for station in line.stations:
                self._by_code[station.code] = (station, line)
                name_l = station.name.lower()
                self._by_name[name_l] = (station, line)
                self._names_lower.append((name_l, station.code.lower(), station, line))

    def get_station(self, code: str) -> Optional[Station]:
        entry = self._by_code.get(code.upper())
        return entry[0] if entry else None

    def get_line(self, line_id: str) -> Optional[Line]:
        return self._by_line_id.get(line_id.upper())

    def find_by_name(self, name_lower: str) -> tuple[Optional[Station], Optional[Line]]:
        entry = self._by_name.get(name_lower)
        return entry if entry else (None, None)

    def search(self, query: str) -> list[tuple[Line, Station]]:
        q = query.lower()
        return [(line, st) for (name, code, st, line) in self._names_lower
                if q in name or q == code]
