import matplotlib
matplotlib.use("Agg")

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.dependencies import set_strava_intelligence
from backend.routers import activities, stats, exports, calendar, sync, athlete
from backend.db import init_db
from strava.strava_intelligence import StravaIntelligence


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize StravaIntelligence singleton
    si = StravaIntelligence(
        workdir=settings.workdir,
        auto_sync=False,
        sync_max_age_hours=settings.sync_max_age_hours,
    )
    set_strava_intelligence(si)
    await init_db()
    yield


app = FastAPI(title="Strava Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["calendar"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(athlete.router, prefix="/api/athlete", tags=["athlete"])

# Serve frontend build if it exists
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
