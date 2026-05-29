from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import Response as RawResponse

from metro.models import NetworkStatus
from metro.serializers import station_to_api_dict
from metro.services.network_service import NetworkService, network_service

router = APIRouter()


def get_service() -> NetworkService:
    return network_service


def _get_network(svc: NetworkService = Depends(get_service)) -> NetworkStatus:
    try:
        return svc.get_network()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


_CACHE_CONTROL = "public, max-age=300"


@router.get("/metro-network", summary="Estado completo de la red de metro")
def get_metro_network(svc: NetworkService = Depends(get_service)):
    try:
        payload = svc.get_network_json()
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return RawResponse(
        content=payload,
        media_type="application/json",
        headers={"Cache-Control": _CACHE_CONTROL},
    )


@router.get("/metro/estacion", summary="Detalle de una estación con horarios")
def get_estacion(
    response: Response,
    nombre: str = Query(..., description="Nombre exacto de la estación (ej: Baquedano)"),
    svc: NetworkService = Depends(get_service),
    network: NetworkStatus = Depends(_get_network),
):
    name_lower = nombre.strip().lower()
    station, line = network.find_by_name(name_lower)
    if not station:
        raise HTTPException(status_code=404, detail=f"Estación '{nombre}' no encontrada en la red")
    svc.enrich_schedule(station)
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return station_to_api_dict(station, line.name)


@router.get("/metro/estacion/{code}", summary="Detalle de una estación por código")
def get_estacion_by_code(
    code: str,
    response: Response,
    svc: NetworkService = Depends(get_service),
    network: NetworkStatus = Depends(_get_network),
):
    station = network.get_station(code.upper().strip())
    if not station:
        raise HTTPException(status_code=404, detail=f"Estación con código '{code}' no encontrada")
    line = network.get_line(station.line_id)
    svc.enrich_schedule(station)
    response.headers["Cache-Control"] = _CACHE_CONTROL
    return station_to_api_dict(station, line.name if line else "")
