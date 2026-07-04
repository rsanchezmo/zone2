import os
from pathlib import Path

_mpl_config_dir = Path(os.environ.get(
    "MPLCONFIGDIR",
    Path(__file__).resolve().parent.parent / ".strava" / "matplotlib",
))
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

_xdg_cache_home = Path(os.environ.get(
    "XDG_CACHE_HOME",
    Path(__file__).resolve().parent.parent / ".strava" / "cache",
))
(_xdg_cache_home / "fontconfig").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(_xdg_cache_home))

import matplotlib
matplotlib.use("Agg")

import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import settings
from backend.dependencies import set_strava_intelligence
from backend.routers import activities, stats, exports, calendar, calendar_feed, sync, athlete, goals, workouts, races, health, garmin, coverage
from backend.routers.sync import _try_claim_sync, _run_sync
from backend.db import init_db
from strava.strava_intelligence import StravaIntelligence


_TOKEN_QS_RE = re.compile(r"(token=)[^&\s\"']+")


class _RedactTokenFilter(logging.Filter):
    """Scrub `token=<secret>` from log records.

    The iCal feed's auth lives in the URL query string so Google's poller
    can subscribe. Uvicorn's access log prints the full request line, which
    would otherwise persist the token in stdout / container logs.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            try:
                record.args = tuple(
                    _TOKEN_QS_RE.sub(r"\1REDACTED", a) if isinstance(a, str) else a
                    for a in record.args
                )
            except Exception:
                pass
        if isinstance(record.msg, str):
            record.msg = _TOKEN_QS_RE.sub(r"\1REDACTED", record.msg)
        return True


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
    logging.getLogger("uvicorn.access").addFilter(_RedactTokenFilter())


async def _periodic_sync_loop(
    si: StravaIntelligence, interval_hours: int, initial_delay_s: int = 30
) -> None:
    """Fire an incremental sync every interval_hours. Runs an initial catch-up
    shortly after startup (initial_delay_s) so a restart/redeploy doesn't leave
    a full interval-long blind window. Skips if a manual sync is already running
    (shares the _sync_lock with the /api/sync endpoint)."""
    log = logging.getLogger("backend.autosync")
    log.info("auto-sync scheduler enabled (every %dh, first run in %ds)",
             interval_hours, initial_delay_s)
    delay = initial_delay_s
    while True:
        try:
            await asyncio.sleep(delay)
            delay = interval_hours * 3600  # subsequent runs at the full interval
            if _try_claim_sync():
                log.info("auto-sync starting")
                await asyncio.to_thread(_run_sync, si, False, True)
                log.info("auto-sync finished")
            else:
                log.info("auto-sync skipped: another sync already running")
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("auto-sync errored, will retry next interval")


async def _periodic_garmin_sync_loop(
    si: StravaIntelligence, interval_hours: int, initial_delay_s: int = 30
) -> None:
    """Refresh Garmin wellness data every interval_hours via sync_recent(days=14).
    Runs an initial catch-up shortly after startup (initial_delay_s) so a
    restart doesn't leave a full interval-long blind window. Independent of the
    Strava lock — both can run concurrently — but shares the Garmin
    /api/garmin/sync claim so a manual sync isn't trampled."""
    # Inline import keeps `routers.garmin` off the module-import path during
    # cold start until it's actually needed.
    from backend.routers.garmin import _try_claim as _try_claim_garmin, _run_garmin_sync
    log = logging.getLogger("backend.garmin_autosync")
    log.info("Garmin auto-sync scheduler enabled (every %dh, first run in %ds)",
             interval_hours, initial_delay_s)
    delay = initial_delay_s
    while True:
        try:
            await asyncio.sleep(delay)
            delay = interval_hours * 3600  # subsequent runs at the full interval
            if _try_claim_garmin():
                log.info("Garmin auto-sync starting")
                await asyncio.to_thread(_run_garmin_sync, si, False)
                log.info("Garmin auto-sync finished")
            else:
                log.info("Garmin auto-sync skipped: another Garmin sync running")
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("Garmin auto-sync errored, will retry next interval")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize StravaIntelligence singleton
    _configure_logging()
    # Anchor Garmin's token cache under .strava/ alongside the Strava token,
    # before StravaIntelligence reads the env var to build its GarminClient.
    os.environ.setdefault("GARMINTOKENS", str(Path(".strava") / "garmin"))
    si = StravaIntelligence(
        workdir=settings.workdir,
        auto_sync=False,
        sync_max_age_hours=settings.sync_max_age_hours,
    )
    # Best-effort Garmin login at startup. Doesn't raise if it fails.
    if si.garmin_client.email:
        await asyncio.to_thread(si.garmin_client.ensure_logged_in)
    set_strava_intelligence(si)
    await init_db()

    # One-time: derive slim per-day chart summaries for any cached Garmin
    # payloads that predate the summary table. Idempotent (no-op once filled),
    # threaded since the first pass parses every stored payload.
    try:
        await asyncio.to_thread(si.garmin_cache.backfill_missing_summaries)
    except Exception:
        logging.getLogger("backend.startup").exception("Garmin summary backfill failed")

    # Warm the in-memory activities cache so the first request after a fresh
    # container (re)deploy doesn't pay the full parquet reload cost. Runs in
    # a thread since pd.read_parquet is blocking.
    startup_log = logging.getLogger("backend.startup")
    startup_log.info("warming activities cache…")
    await asyncio.to_thread(si.strava_activities_cache._load_to_memory)
    startup_log.info("activities cache warm")

    sync_task: asyncio.Task | None = None
    if settings.auto_sync_hours > 0:
        sync_task = asyncio.create_task(_periodic_sync_loop(si, settings.auto_sync_hours))

    garmin_sync_task: asyncio.Task | None = None
    if settings.auto_garmin_sync_hours > 0 and si.garmin_client.email:
        garmin_sync_task = asyncio.create_task(
            _periodic_garmin_sync_loop(si, settings.auto_garmin_sync_hours)
        )

    try:
        yield
    finally:
        for task in (sync_task, garmin_sync_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


app = FastAPI(
    title="Strava Intelligence",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

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
app.include_router(calendar_feed.router, prefix="/api", tags=["calendar-feed"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(athlete.router, prefix="/api/athlete", tags=["athlete"])
app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
app.include_router(workouts.router, prefix="/api/workouts", tags=["workouts"])
app.include_router(races.router, prefix="/api/races", tags=["races"])
app.include_router(garmin.router, prefix="/api/garmin", tags=["garmin"])
app.include_router(coverage.router, prefix="/api/coverage", tags=["coverage"])

# Serve frontend build if it exists
class _SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html on 404 so the React router
    can handle unknown paths client-side. Without this, deep links and hard
    refreshes (e.g. /calendar, /activities/123) return 404 from the server."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as ex:
            if ex.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(frontend_dist), html=True), name="frontend")
