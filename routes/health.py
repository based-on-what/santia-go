from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    return {"mensaje": "API Red Santiago funcionando", "docs": "/docs"}
