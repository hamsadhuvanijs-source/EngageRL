from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth.router import router as auth_router
from app.chats.router import router as chats_router
from app.config import get_settings
from app.generation.router import router as generation_router
from app.ingestion.router import router as ingestion_router
from app.rl.router import router as rl_router
from app.sessions.router import router as sessions_router
from app.stats.router import router as stats_router
from app.telemetry.router import router as telemetry_router
from app.tutor.router import router as tutor_router

settings = get_settings()

app = FastAPI(title="EngageRL API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path(settings.generated_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.generated_dir), name="media")

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(ingestion_router)
app.include_router(generation_router)
app.include_router(sessions_router)
app.include_router(telemetry_router)
app.include_router(rl_router)
app.include_router(stats_router)
app.include_router(tutor_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
