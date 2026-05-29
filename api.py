import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routes.health import router as health_router
from routes.ibus import router as ibus_router
from routes.metro import router as metro_router

app = FastAPI(
    title="API Red de Santiago",
    description="Paraderos iBUS + Metro de Santiago",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api")
app.include_router(metro_router, prefix="/api")
app.include_router(metro_router, prefix="", include_in_schema=False)
app.include_router(ibus_router, prefix="/api")
app.include_router(ibus_router, prefix="", include_in_schema=False)

_PUBLIC = Path(__file__).parent / "public"
if _PUBLIC.exists():
    app.mount("/", StaticFiles(directory=str(_PUBLIC), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
