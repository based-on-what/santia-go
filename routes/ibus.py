import os

from fastapi import APIRouter, HTTPException

from metro.infrastructure.ibus import IBusClient, IBusProxyError

router = APIRouter()

# Singleton — one session/pool for lifetime of process
_ibus_client = IBusClient(os.environ.get("IBUS_PROXY_URL", ""))


@router.get("/paradero/{paradero}", summary="Buses en tiempo real para un paradero (iBUS)")
def consultar_paradero(paradero: str):
    try:
        return _ibus_client.query_stop(paradero.upper().strip())
    except IBusProxyError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))
