"""
Scraper for Metro de Santiago.

Data sources:
  - https://www.metro.cl/api/estadoRedDetalle.php       — network status (JSON)
  - https://www.metro.cl/api/horariosEstacion.php?cod=  — station schedules (JSON)
  - https://www.metro.cl/el-viaje/estaciones/?estacion= — station detail page (HTML)
  - https://apis.digital.gob.cl/fl/feriados/            — Chilean public holidays (JSON)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .models import (
    AccessPoint,
    DaySchedule,
    Line,
    NetworkStatus,
    Station,
    StationSchedule,
    TrainTimes,
)

logger = logging.getLogger(__name__)

# ── Endpoints ──────────────────────────────────────────────────────────────────

_BASE = "https://www.metro.cl"
STATUS_API    = f"{_BASE}/api/estadoRedDetalle.php"
SCHEDULE_API  = f"{_BASE}/api/horariosEstacion.php"
STATION_PAGE  = f"{_BASE}/el-viaje/estaciones/"
HOLIDAY_API   = "https://apis.digital.gob.cl/fl/feriados/{year}/{month}/{day}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-CL,es;q=0.9",
}

# ── Low-level HTTP helpers ─────────────────────────────────────────────────────

def _get_json(url: str, params: dict | None = None) -> dict | list | None:
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.error("GET %s failed: %s", url, exc)
        return None


def _get_html(url: str, params: dict | None = None) -> str | None:
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.error("GET %s failed: %s", url, exc)
        return None


# ── Public holiday check ───────────────────────────────────────────────────────

def is_today_holiday() -> bool:
    """Returns True if today is a Chilean public holiday."""
    now = datetime.now()
    url = HOLIDAY_API.format(year=now.year, month=now.month, day=now.day)
    data = _get_json(url)
    return isinstance(data, list) and len(data) > 0


# ── Network status (all lines + stations) ─────────────────────────────────────

def fetch_network_status() -> Optional[NetworkStatus]:
    """
    Fetches operational status for all lines and stations from the JSON API.
    Returns a NetworkStatus with no schedules attached (fast, single request).
    """
    data = _get_json(STATUS_API)
    if not data:
        return None

    lines: list[Line] = []
    has_issues = False

    for line_key, line_data in data.items():
        # API keys are "l1", "l2", "l4a", etc. → normalise to "L1", "L4A"
        line_id = line_key.upper()
        suffix = line_id[1:]                        # "1", "2", "4A"
        line_name = f"Línea {suffix}"

        operational = str(line_data.get("estado", "0")) == "1"
        message = line_data.get("mensaje", "").strip()
        if not operational:
            has_issues = True

        stations: list[Station] = []
        for st in line_data.get("estaciones", []):
            enabled = str(st.get("estado", "0")) == "1"
            if not enabled:
                has_issues = True

            raw_transfers = st.get("combinacion", "").strip()
            transfers = [t.strip() for t in raw_transfers.split(",") if t.strip()]

            stations.append(Station(
                code=st["codigo"],
                name=st["nombre"],
                line_id=line_id,
                enabled=enabled,
                status_description=st.get("descripcion", "").strip(),
                message=st.get("mensaje", "").strip(),
                transfers=transfers,
            ))

        lines.append(Line(
            id=line_id,
            name=line_name,
            operational=operational,
            message=message,
            stations=stations,
        ))

    return NetworkStatus(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        lines=lines,
        has_issues=has_issues,
    )


# ── Per-station schedule ───────────────────────────────────────────────────────

def _day_schedule(data: dict) -> DaySchedule:
    return DaySchedule(
        weekdays=data.get("lunes_viernes", "-").strip(),
        saturday=data.get("sabado", "-").strip(),
        holidays=data.get("domingo", "-").strip(),
    )


def fetch_station_schedule(
    code: str,
) -> tuple[Optional[StationSchedule], Optional[TrainTimes], Optional[TrainTimes]]:
    """
    Fetches schedule for a single station by its code (e.g. "BA").
    Returns (StationSchedule, terminal_a TrainTimes, terminal_b TrainTimes).
    Any element may be None if the API returns no data.
    """
    data = _get_json(SCHEDULE_API, params={"cod": code})
    if not data:
        return None, None, None

    estacion = data.get("estacion", {})
    schedule = StationSchedule(
        open=_day_schedule(estacion.get("abrir", {})),
        close=_day_schedule(estacion.get("cerrar", {})),
    )

    def _train_times(raw: dict) -> Optional[TrainTimes]:
        if not raw:
            return None
        return TrainTimes(
            name=raw.get("nombre", "").strip(),
            first_train=_day_schedule(raw.get("primer_tren", {})),
            last_train=_day_schedule(raw.get("ultimo_tren", {})),
        )

    tren = data.get("tren", {})
    terminal_a = _train_times(tren.get("estacion_a"))
    terminal_b = _train_times(tren.get("estacion_b"))

    return schedule, terminal_a, terminal_b


# ── Per-station detail page (accesses + services) ─────────────────────────────

def fetch_station_details(
    code: str,
) -> tuple[list[AccessPoint], dict[str, list[str]]]:
    """
    Scrapes the station detail page for access points (accesos, elevators)
    and station services (commerce, culture, etc.).

    URL: https://www.metro.cl/el-viaje/estaciones/?estacion={CODE}
    """
    html = _get_html(STATION_PAGE, params={"estacion": code})
    if not html:
        return [], {}

    soup = BeautifulSoup(html, "html.parser")
    accesses: list[AccessPoint] = []
    services: dict[str, list[str]] = {}

    # ── Accesses & elevators ──────────────────────────────────────────────────
    # Each <p class="p-left-15"> inside #estaccesibilidad is one access point.
    # Operational items have a <span class="font-color-verde">,
    # out-of-service items have <span class="font-color-rojo">.
    acc_section = soup.find("div", id="estaccesibilidad")
    if acc_section:
        for p in acc_section.find_all("p", class_="p-left-15"):
            operational = bool(p.find("span", class_="font-color-verde"))
            # Strip icon glyphs and surrounding whitespace from the text
            name = p.get_text(" ", strip=True)
            # Remove Font Awesome glyph characters (they show as tofu or icons)
            name = " ".join(name.split())
            if name:
                accesses.append(AccessPoint(name=name, operational=operational))

    # ── Station services ──────────────────────────────────────────────────────
    # Each Bootstrap card in #estequipamiento is a category (Servicios Generales,
    # Accesibilidad, Comercio, Cultura, …).
    svc_section = soup.find("div", id="estequipamiento")
    if svc_section:
        for card in svc_section.find_all("div", class_="card"):
            body = card.find("div", class_="card-body")
            if not body:
                continue
            title_tag = body.find("strong")
            if not title_tag:
                continue
            category = title_tag.get_text(strip=True)
            items = [li.get_text(" ", strip=True) for li in body.find_all("li")]
            if items:
                services[category] = items

    return accesses, services


# ── Full scrape ────────────────────────────────────────────────────────────────

def fetch_all(
    include_schedules: bool = True,
    include_details: bool = False,
    progress_callback=None,
) -> Optional[NetworkStatus]:
    """
    Full scrape combining all data sources.

    Args:
        include_schedules: fetch schedule for every unique station (~136 API calls).
        include_details:   also scrape each station page for accesses/services
                           (~136 HTML pages — significantly slower).
        progress_callback: optional callable(current, total, station_name) for
                           progress reporting.

    Returns a fully populated NetworkStatus, or None on failure.
    """
    network = fetch_network_status()
    if not network:
        return None

    if not include_schedules and not include_details:
        return network

    # Deduplicate codes (transfer stations appear on two lines)
    unique_stations: dict[str, Station] = {}
    all_station_refs: list[Station] = []
    for line in network.lines:
        for station in line.stations:
            all_station_refs.append(station)
            if station.code not in unique_stations:
                unique_stations[station.code] = station

    total = len(unique_stations)

    for i, (code, station) in enumerate(unique_stations.items()):
        if progress_callback:
            progress_callback(i + 1, total, station.name)

        if include_schedules:
            sched, term_a, term_b = fetch_station_schedule(code)
            station.schedule = sched
            station.terminal_a = term_a
            station.terminal_b = term_b

        if include_details:
            accesses, services = fetch_station_details(code)
            station.accesses = accesses
            station.services = services

        # Propagate schedule/details to the same station on other lines
        # (transfer stations share a code but are separate Station objects)
        for ref in all_station_refs:
            if ref.code == code and ref is not station:
                if include_schedules:
                    ref.schedule = station.schedule
                    ref.terminal_a = station.terminal_a
                    ref.terminal_b = station.terminal_b
                if include_details:
                    ref.accesses = station.accesses
                    ref.services = station.services

    return network
