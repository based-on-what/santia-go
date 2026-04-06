"""
CLI for Metro de Santiago scraper.

Usage:
    python metro_cli.py [COMMAND] [OPTIONS]

Commands:
    status   Show overall network status
    list     List all stations (with optional filters)
    station  Show full details for one station
    search   Search stations by name
    refresh  Force-fetch fresh data and update the cache
    export   Export all data to a JSON file
"""

from __future__ import annotations

import json
import sys
from typing import Optional

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .cache import cache_age, load_cache, save_cache
from .models import Line, NetworkStatus, Station
from .scraper import (
    fetch_all,
    fetch_network_status,
    fetch_station_details,
    fetch_station_schedule,
)

console = Console()

# ── Colour palette (matches metro.cl line colours) ────────────────────────────

_LINE_COLORS: dict[str, str] = {
    "L1":  "red",
    "L2":  "yellow3",
    "L3":  "dark_orange",
    "L4":  "cornflower_blue",
    "L4A": "cyan",
    "L5":  "green",
    "L6":  "magenta",
}

_DEFAULT_COLOR = "white"


def _lc(line_id: str) -> str:
    return _LINE_COLORS.get(line_id.upper(), _DEFAULT_COLOR)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _load_network(no_cache: bool, full: bool = False) -> Optional[NetworkStatus]:
    """Load from cache or fetch from metro.cl."""
    if not no_cache:
        network = load_cache()
        if network:
            age = cache_age()
            secs = int(age.total_seconds()) if age else 0
            console.print(
                f"[dim]Usando caché ({secs}s de antigüedad). "
                f"Usa --no-cache para datos frescos.[/dim]"
            )
            return network

    with console.status("[bold green]Obteniendo datos desde metro.cl…"):
        network = fetch_all(
            include_schedules=True,
            include_details=full,
        )

    if network:
        save_cache(network)
    else:
        console.print("[bold red]Error al conectarse a metro.cl.[/bold red]")
    return network


def _status_badge(enabled: bool) -> str:
    return "[green]●  Habilitada[/green]" if enabled else "[red]✗  No habilitada[/red]"


def _transfers_fmt(transfers: list[str]) -> str:
    if not transfers:
        return "-"
    parts = []
    for t in transfers:
        c = _lc(t)
        parts.append(f"[{c}]{t}[/{c}]")
    return "  ".join(parts)


# ── CLI group ──────────────────────────────────────────────────────────────────

@click.group()
@click.version_option("1.0.0", prog_name="metro")
def cli():
    """Metro de Santiago — herramienta de consulta desde terminal."""


# ── status ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--no-cache", is_flag=True, help="Ignorar caché y obtener datos frescos.")
def status(no_cache: bool):
    """Muestra el estado operacional de toda la red."""
    network = _load_network(no_cache)
    if not network:
        sys.exit(1)

    overall = (
        "[bold green]SIN INCIDENCIAS[/bold green]"
        if not network.has_issues
        else "[bold red]CON INCIDENCIAS[/bold red]"
    )
    console.print(
        Panel(
            f"Estado de la red: {overall}",
            title="[bold]Metro de Santiago[/bold]",
            subtitle=f"[dim]{network.timestamp}[/dim]",
            border_style="blue",
        )
    )

    for line in network.lines:
        c = _lc(line.id)
        line_badge = "[green]●[/green]" if line.operational else "[red]✗[/red]"
        header = f"{line_badge} [{c}][bold]{line.name}[/bold][/{c}]"
        if line.message:
            header += f"  [yellow]{line.message}[/yellow]"

        disabled = line.disabled_stations
        if disabled:
            header += f"  [red]({len(disabled)} no habilitada{'s' if len(disabled) > 1 else ''})[/red]"

        console.print(header)
        for st in disabled:
            console.print(f"     [red]✗[/red] {st.name} — [dim]{st.status_description}[/dim]")
            if st.message:
                console.print(f"       [yellow]{st.message}[/yellow]")

    console.print()


# ── list ───────────────────────────────────────────────────────────────────────

@cli.command(name="list")
@click.option("--no-cache", is_flag=True)
@click.option("--line", "-l", default=None, metavar="ID",
              help="Filtrar por línea: L1, L2, L3, L4, L4A, L5, L6.")
@click.option("--issues", is_flag=True, help="Mostrar solo estaciones no habilitadas.")
def list_stations(no_cache: bool, line: Optional[str], issues: bool):
    """Lista todas las estaciones con su estado actual."""
    network = _load_network(no_cache)
    if not network:
        sys.exit(1)

    table = Table(
        title="Estaciones Metro de Santiago",
        box=box.ROUNDED,
        header_style="bold",
        show_lines=False,
    )
    table.add_column("Cód.", style="dim", width=5, no_wrap=True)
    table.add_column("Estación", min_width=28)
    table.add_column("Línea", width=10, no_wrap=True)
    table.add_column("Estado", min_width=16)
    table.add_column("Combinación", min_width=10)
    table.add_column("Horario L-V", width=14, justify="center")

    for ln in network.lines:
        if line and ln.id.lower() != line.lower():
            continue
        c = _lc(ln.id)
        for st in ln.stations:
            if issues and st.enabled:
                continue

            schedule_str = "-"
            if st.schedule:
                o = st.schedule.open.weekdays
                cl = st.schedule.close.weekdays
                if o != "-" and cl != "-":
                    schedule_str = f"{o} – {cl}"

            table.add_row(
                st.code,
                st.name,
                f"[{c}]{ln.name}[/{c}]",
                _status_badge(st.enabled),
                _transfers_fmt(st.transfers),
                schedule_str,
            )

    console.print(table)
    total = sum(len(ln.stations) for ln in network.lines
                if not line or ln.id.lower() == line.lower())
    console.print(f"[dim]{total} estación(es)  ·  {network.timestamp}[/dim]\n")


# ── station ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("code")
@click.option("--no-cache", is_flag=True)
@click.option("--full", is_flag=True,
              help="Incluir accesos y servicios (requiere scraping adicional).")
def station(code: str, no_cache: bool, full: bool):
    """Muestra todos los detalles de una estación (por código, ej: BA, SP)."""
    network = _load_network(no_cache)
    if not network:
        sys.exit(1)

    st = network.get_station(code)
    if not st:
        console.print(f"[red]No se encontró la estación con código '{code.upper()}'.[/red]")
        console.print("[dim]Usa 'metro list' para ver todos los códigos disponibles.[/dim]")
        sys.exit(1)

    # Fetch schedule if not in cache
    if st.schedule is None:
        with console.status(f"Obteniendo horarios para {st.code}…"):
            st.schedule, st.terminal_a, st.terminal_b = fetch_station_schedule(st.code)

    # Optionally fetch detail page
    if full and not st.accesses and not st.services:
        with console.status(f"Obteniendo accesos y servicios para {st.code}…"):
            st.accesses, st.services = fetch_station_details(st.code)

    c = _lc(st.line_id)
    sc = "green" if st.enabled else "red"

    # ── Header panel ──────────────────────────────────────────────────────────
    header = Text()
    header.append(f"{st.name}\n", style=f"bold {c}")
    header.append(f"Código: {st.code}   Línea: ", style="dim")
    header.append(st.line_id, style=f"bold {c}")
    if st.transfers:
        header.append("   Combinación: ", style="dim")
        header.append(", ".join(st.transfers), style="cyan bold")
    header.append(f"\nEstado: ", style="")
    header.append("Habilitada" if st.enabled else "No habilitada", style=f"bold {sc}")
    if st.status_description:
        header.append(f"  ({st.status_description})", style="dim")
    if st.message:
        header.append(f"\n⚠  {st.message}", style="yellow")

    console.print(Panel(header, border_style=c, title="Estación"))

    # ── Schedule ──────────────────────────────────────────────────────────────
    if st.schedule:
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        t.add_column("", style="dim", width=12)
        t.add_column("Lun – Vie", justify="center", min_width=10)
        t.add_column("Sábado", justify="center", min_width=10)
        t.add_column("Dom / Festivo", justify="center", min_width=13)

        t.add_row(
            "Apertura",
            st.schedule.open.weekdays,
            st.schedule.open.saturday,
            st.schedule.open.holidays,
        )
        t.add_row(
            "Cierre",
            st.schedule.close.weekdays,
            st.schedule.close.saturday,
            st.schedule.close.holidays,
        )
        console.print(Panel(t, title="Horario de Estación", border_style="blue"))

    # ── Train times ───────────────────────────────────────────────────────────
    if st.terminal_a or st.terminal_b:
        t = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        t.add_column("Hacia", min_width=22)
        t.add_column("", style="dim", width=14)
        t.add_column("Lun – Vie", justify="center", min_width=10)
        t.add_column("Sábado", justify="center", min_width=10)
        t.add_column("Dom / Festivo", justify="center", min_width=13)

        for terminal in (st.terminal_a, st.terminal_b):
            if not terminal:
                continue
            t.add_row(
                f"[bold]{terminal.name}[/bold]",
                "Primer tren",
                terminal.first_train.weekdays,
                terminal.first_train.saturday,
                terminal.first_train.holidays,
            )
            t.add_row(
                "",
                "Último tren",
                terminal.last_train.weekdays,
                terminal.last_train.saturday,
                terminal.last_train.holidays,
            )

        console.print(Panel(t, title="Trenes (primer / último)", border_style="blue"))

    # ── Accesses (only when --full) ───────────────────────────────────────────
    if st.accesses:
        t = Table(box=box.SIMPLE, show_header=False)
        t.add_column("", width=3)
        t.add_column("Acceso / Ascensor")
        for acc in st.accesses:
            icon = "[green]●[/green]" if acc.operational else "[red]✗[/red]"
            t.add_row(icon, acc.name)
        console.print(Panel(t, title="Accesibilidad", border_style="green"))

    # ── Services (only when --full) ───────────────────────────────────────────
    if st.services:
        txt = Text()
        for cat, items in st.services.items():
            txt.append(f"{cat}\n", style="bold")
            for item in items:
                txt.append(f"  • {item}\n")
        console.print(Panel(txt, title="Servicios de estación", border_style="yellow"))

    if full and not st.accesses and not st.services:
        console.print("[dim]No se encontraron datos de accesos ni servicios para esta estación.[/dim]")


# ── search ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--no-cache", is_flag=True)
def search(query: str, no_cache: bool):
    """Busca estaciones por nombre o código (ej: 'baquedano', 'BA')."""
    network = _load_network(no_cache)
    if not network:
        sys.exit(1)

    results = network.search(query)
    if not results:
        console.print(f"[yellow]Sin resultados para '{query}'.[/yellow]")
        return

    table = Table(
        title=f"Resultados para «{query}»",
        box=box.ROUNDED,
        header_style="bold",
    )
    table.add_column("Cód.", style="dim", width=5)
    table.add_column("Estación", min_width=28)
    table.add_column("Línea", width=10)
    table.add_column("Estado", min_width=16)
    table.add_column("Combinación", min_width=10)

    for line, st in results:
        c = _lc(line.id)
        table.add_row(
            st.code,
            st.name,
            f"[{c}]{line.name}[/{c}]",
            _status_badge(st.enabled),
            _transfers_fmt(st.transfers),
        )

    console.print(table)


# ── refresh ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--full", is_flag=True,
              help="Incluir accesos y servicios de cada estación (lento, ~136 páginas).")
def refresh(full: bool):
    """Fuerza la obtención de datos frescos y actualiza el caché."""

    total_ref: list[int] = [0]

    def _progress(current: int, total: int, name: str):
        total_ref[0] = total
        console.print(
            f"  [dim][{current:3d}/{total}][/dim] {name}",
            end="\r",
        )

    console.print("[bold green]Actualizando datos desde metro.cl…[/bold green]")
    network = fetch_all(
        include_schedules=True,
        include_details=full,
        progress_callback=_progress,
    )
    console.print()  # newline after \r progress

    if not network:
        console.print("[bold red]Error al obtener datos.[/bold red]")
        sys.exit(1)

    save_cache(network)
    n_lines = len(network.lines)
    n_stations = sum(len(l.stations) for l in network.lines)
    console.print(
        f"[green]✓[/green] Caché actualizado: "
        f"[bold]{n_lines}[/bold] líneas, [bold]{n_stations}[/bold] estaciones."
    )
    if network.has_issues:
        console.print("[yellow]⚠  La red tiene incidencias. Usa 'metro status' para más detalle.[/yellow]")


# ── export ─────────────────────────────────────────────────────────────────────

@cli.command(name="export")
@click.option("--no-cache", is_flag=True)
@click.option("--output", "-o", default="metro_data.json", show_default=True,
              help="Nombre del archivo de salida.")
@click.option("--full", is_flag=True,
              help="Incluir accesos y servicios (requiere --no-cache).")
def export_json(no_cache: bool, output: str, full: bool):
    """Exporta todos los datos a un archivo JSON."""
    network = _load_network(no_cache, full=full)
    if not network:
        sys.exit(1)

    def _day(d):
        return {"weekdays": d.weekdays, "saturday": d.saturday, "holidays": d.holidays}

    def _schedule(s):
        if s is None:
            return None
        return {"open": _day(s.open), "close": _day(s.close)}

    def _train(t):
        if t is None:
            return None
        return {"name": t.name, "first_train": _day(t.first_train), "last_train": _day(t.last_train)}

    data = {
        "timestamp": network.timestamp,
        "has_issues": network.has_issues,
        "lines": [
            {
                "id": line.id,
                "name": line.name,
                "operational": line.operational,
                "message": line.message,
                "stations": [
                    {
                        "code": st.code,
                        "name": st.name,
                        "line_id": st.line_id,
                        "enabled": st.enabled,
                        "status_description": st.status_description,
                        "message": st.message,
                        "transfers": st.transfers,
                        "schedule": _schedule(st.schedule),
                        "terminal_a": _train(st.terminal_a),
                        "terminal_b": _train(st.terminal_b),
                        "accesses": [
                            {"name": a.name, "operational": a.operational}
                            for a in st.accesses
                        ],
                        "services": st.services,
                    }
                    for st in line.stations
                ],
            }
            for line in network.lines
        ],
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    console.print(f"[green]✓[/green] Exportado a [bold]{output}[/bold]")
