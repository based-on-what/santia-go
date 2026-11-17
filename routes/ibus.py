import re

from fastapi import APIRouter, HTTPException

from metro.infrastructure.redcl import RedClClient, RedClError

router = APIRouter()

# Every stop_id in public/data/paraderos_santiago.geojson is P[A-J] + 1-4 digits; this leaves headroom.
STOP_CODE = re.compile(r"P[A-Z]\d{1,5}")

# Singleton: one session and one cached red.cl token for the life of the process.
_redcl_client = RedClClient()


@router.get("/paradero/{paradero}", summary="Buses en tiempo real para un paradero (red.cl)")
def consultar_paradero(paradero: str):
    stop = paradero.upper().strip()
    if not STOP_CODE.fullmatch(stop):
        raise HTTPException(status_code=422, detail="Codigo de paradero invalido")
    try:
        return _redcl_client.query_stop(stop)
    except RedClError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
