import matplotlib
matplotlib.use("Agg")

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.dependencies import set_strava_intelligence
from backend.routers import activities, stats, exports, calendar, sync, athlete, goals, workouts, races, health
from backend.routers.sync import _try_claim_sync, _run_sync
from backend.db import init_db
from strava.strava_intelligence import StravaIntelligence


def _configure_logging() -> None:
    """Wire our app + strava loggers into stdout with a consistent format.

    Uses force=True so we override whatever uvicorn set up by default —
    otherwise our `logger.info(...)` calls in strava/ would get swallowed
    or formatted differently from FastAPI's own request logs.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


async def _periodic_sync_loop(si: StravaIntelligence, interval_hours: int) -> None:
    """Fire an incremental sync every interval_hours. Skips if a manual sync
    is already running (shares the _sync_lock with the /api/sync endpoint)."""
    log = logging.getLogger("backend.autosync")
    log.info("auto-sync scheduler enabled (every %dh)", interval_hours)
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            if _try_claim_sync():
                log.info("auto-sync starting")
                await asyncio.to_thread(_run_sync, si, False, False)
                log.info("auto-sync finished")
            else:
                log.info("auto-sync skipped: another sync already running")
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("auto-sync errored, will retry next interval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize StravaIntelligence singleton
    _configure_logging()
    si = StravaIntelligence(
        workdir=settings.workdir,
        auto_sync=False,
        sync_max_age_hours=settings.sync_max_age_hours,
    )
    set_strava_intelligence(si)
    await init_db()

    sync_task: asyncio.Task | None = None
    if settings.auto_sync_hours > 0:
        sync_task = asyncio.create_task(_periodic_sync_loop(si, settings.auto_sync_hours))

    try:
        yield
    finally:
        if sync_task is not None:
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Strava Intelligence", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(activities.router, prefix="/api/activities", tags=["activities"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(calendar.router, prefix="/api/calendar", tags=["calendar"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(athlete.router, prefix="/api/athlete", tags=["athlete"])
app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
app.include_router(workouts.router, prefix="/api/workouts", tags=["workouts"])
app.include_router(races.router, prefix="/api/races", tags=["races"])

# Serve frontend build if it exists
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
