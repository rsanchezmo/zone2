# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

z2 is a full-stack application for analyzing and visualizing Strava activities locally, without Strava Premium. It syncs activities via the Strava API, caches them as Parquet files, and provides a React web app with dashboards, personal records, training calendar, and map visualizations — plus a Telegram bot and CLI-generated neon-styled PNG reports.

## Setup & Running

```bash
# Install dependencies (Poetry required, Python 3.12+)
poetry install

# Run the web app (backend + frontend dev servers)
python run_dev.py
# Backend: http://localhost:8000 (FastAPI/Uvicorn)
# Frontend: http://localhost:5173 (Vite dev server, proxies /api to backend)

# Or run individually
cd frontend && npm run dev     # Frontend only
uvicorn backend.app:app --port 8000  # Backend only

# Run the main script (example usage / sandbox)
python main.py

# Run the Telegram bot (requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)
python telegram_bot.py

# Docker deployment (includes Cloudflare Tunnel support)
docker-compose up
```

**Environment variables** (`.env` file in project root):
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` — required for API access
- `STRAVA_WEB_*` — backend config (loaded via Pydantic settings in `backend/config.py`)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional, for the Telegram bot
- `CLOUDFLARE_TUNNEL_TOKEN` — optional, for Docker deployment with Cloudflare Tunnel

There are no tests or CI configured. The frontend has ESLint (react-hooks v7 / React Compiler rules) — keep `cd frontend && npm run lint` and `npx tsc -b` at zero errors.

## Architecture

### Core Class Hierarchy

`Zone2` (in `zone2/core.py`) is the main orchestrator that wires everything together:

```
Zone2
├── StravaEndpoint          — Strava API client (OAuth, activity/stream fetching)
├── StravaActivitiesCache   — Local Parquet-based activity storage with lazy in-memory loading
├── StravaUserCache          — Cached user profile/zones data
├── StravaAnalytics          — Computes stats (year-in-sport, weekly reports, HR zones, VO2max)
└── StravaVisualizer         — All matplotlib visualizations (heatmaps, dashboards, reports)
```

### Data Flow

1. **Sync**: `StravaEndpoint` fetches activities from Strava API → `StravaActivitiesCache` stores them as monthly Parquet files under `.strava/activities/{year}/{YYYY-MM}.parquet`
2. **Streams**: High-res GPS/HR data is fetched separately per-activity and stored as JSON within the Parquet columns
3. **Analysis**: `StravaAnalytics` reads from the cache and computes aggregated stats (returns plain dicts keyed by `StrEnum` feature classes: `YearInSportFeatures`, `AllYearInSportFeatures`, `WeeklyReportFeatures`)
4. **Visualization**: `StravaVisualizer` takes analytics output and generates PNG files in `{workdir}/` subdirectories
5. **Web API**: FastAPI backend (`backend/`) exposes analytics and cache data as REST endpoints consumed by the React frontend

### Web App (Frontend + Backend)

**Backend** (`backend/`): FastAPI app with 8 API routers at `/api/*`:
- `activities.py` — List, filter, sort activities; polylines for maps; similar activities
- `stats.py` — Weekly reports, year-in-sport, efficiency factor, performance frontier, personal records, streaks
- `calendar.py` — Training session CRUD, scoring
- `exports.py` — PNG image generation (weekly reports, heatmaps, activity plots)
- `sync.py` — Background sync tasks, stream backfill, cache status
- `athlete.py` — Profile, rate limits, HR zones
- `goals.py` — Yearly goal CRUD with progress tracking
- `workouts.py` — Workout template management with segments
- `dependencies.py` — DI providing `Zone2` singleton
- `config.py` — Pydantic settings (`workdir`, `cors_origins`, `sync_max_age_hours`)
- `db.py` — SQLite via aiosqlite at `.strava/calendar.db` (tables: `training_sessions`, `goals`, `workout_templates`)

**Frontend** (`frontend/`): React 19 + TypeScript + Vite SPA:
- **Stack**: TailwindCSS 4, React Router 7, TanStack React Query, Recharts, Leaflet
- **Pages** (8): Dashboard, Activities, ActivityDetail, Calendar, Aggregations, PersonalRecords, Profile, Workouts
- **Layout**: `AppShell` with dock navigation, dark/light theme support
- **API layer**: Axios client at `/api`, 40+ React Query hooks in `api/hooks.ts`
- **Dev**: Vite dev server on :5173 proxies `/api` to backend on :8000

**Deployment**: Multi-stage Dockerfile (Node 22 builds frontend → Python 3.12 serves via Uvicorn); docker-compose with optional Cloudflare Tunnel

### Map Matching (separate entry point)

`StravaMapMatcher` uses OSMnx + LeuvenMapMatching to match GPS tracks to OSM road networks. It operates on GeoDataFrames built from streams via `get_activities_as_gdf_from_streams()`. Returns `MatchResult` dataclass per activity.

### Key Conventions

- All geo data uses `EPSG:4326` (BASE_CRS) as base, projected to `EPSG:3857` (WEB_MERCATOR_CRS) for visualization
- Speed is stored in m/s (Strava API native); conversion to pace/speed uses `convert_speed()` / `format_pace_or_speed()` in `zone2/utils.py` which auto-detects sport category
- Sport categories are classified via string matching in `zone2/utils.py`: running, cycling, swimming
- Visualizations use a consistent dark/neon aesthetic with configurable `neon_color` parameters
- Output images for reports use Instagram Story aspect ratio (9:16)
- Token/auth data cached in `.strava/token.json`; activity metadata in `.strava/metadata.json`
- `telegram_bot.py` uses `matplotlib.use("Agg")` for headless rendering and runs blocking Strava operations in a thread pool
- Frontend uses dark theme by default with custom surface color tokens and neon accents

### Files of Note

- `run_dev.py` — Runs backend + frontend dev servers concurrently
- `zone2/mcp.py` — Placeholder for future MCP server integration (currently empty)
- `main.py` — Sandbox/example script, not a library entry point
- `cache/` — SHA-based JSON cache files (for user data caching via `StravaUserCache`)
