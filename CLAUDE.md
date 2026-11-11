# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

z2 is a full-stack application for analyzing and planning training locally. It syncs activities via the Strava API (and, optionally, wellness data, workouts and courses with Garmin Connect), caches them as Parquet files, and provides a React web app with a training calendar, analytics, records, street coverage maps and an AI coach — plus a Telegram bot and neon-styled PNG reports.

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

# Docker deployment (includes Cloudflare Tunnel support, see DEPLOY.md)
docker compose up
```

**Environment variables** (`.env` file in the project root, loaded by `backend/config.load_settings()` from the checkout whatever the working directory; the real environment wins):
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` — required for API access
- `STRAVA_WEB_*` — backend config (loaded via Pydantic settings in `backend/config.py`)
- `STRAVA_WEB_DATA_DIR` / `STRAVA_WEB_WORKDIR` — optional; where z2 keeps its data (activities, streams, tokens, `calendar.db`) and its street maps and exports. Default `.strava/` and `zone2_workdir/` in the checkout (`zone2/paths.py`), which is also where the Docker volumes mount
- `GARMIN_EMAIL` / `GARMIN_PASSWORD` — optional, enables the Garmin Connect integration; `GARMINTOKENS` optionally moves its token cache (default `garmin/` in the data dir)
- `OPENAI_API_KEY` — optional, for the coach agent
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional, for the Telegram bot (`STRAVA_WORKDIR` gives it its own workdir; else the app's)
- `CLOUDFLARE_TUNNEL_TOKEN` — optional, for Docker deployment with Cloudflare Tunnel
- `STRAVA_WEB_CARTO_API_KEY` — optional; without it Leaflet basemaps fall back to OSM, since unkeyed CARTO tiles are watermarked

`tests/` holds the pytest suite (Poetry dev group): the numeric core, the services and the agent's tools against a throwaway SQLite database, coverage and the planner on small synthetic street grids, the API on a synthetic data directory, and the layering rules below (`test_structure.py`). Tests build synthetic activities and streams in code, never real data (the repo is public); `tests/conftest.py` points the data dir and workdir at temp dirs, hides `.env` and refuses network connections, so nothing reaches Strava, Garmin or a model. Run `poetry run pytest -q` (a few seconds); a known bug stays as a strict `xfail` with its reason. Time-dependent code takes its "now" from `z2.clock`, which tests pin. CI (`.github/workflows/ci.yml`) runs ESLint (react-hooks v7 / React Compiler rules), the frontend build (`tsc -b` + Vite), ruff (E9/F only), an import smoke test (`import backend.app, telegram_bot`), the tests and `docker build .` — keep `cd frontend && npm run lint` and `npx tsc -b` at zero errors.

## Architecture

### Core Class Hierarchy

`Zone2(workdir, data_dir)` (in `zone2/core.py`) is the main orchestrator that wires everything together. Each entry point (the app, the bot, `main.py`, scripts) passes its data directory down; `zone2.paths.DataDir` names every path under it:

```
Zone2
├── StravaEndpoint          — Strava API client (OAuth, activity/stream fetching)
├── StravaActivitiesCache   — Local Parquet-based activity storage with lazy in-memory loading
├── Clock                   — The athlete's today and now (`zone2/clock.py`, see Key Conventions)
├── StravaUserCache         — Athlete profile/zones (in memory) and gear (`gear.json`)
├── GarminClient            — Optional Garmin Connect client (wellness, workouts, courses); off without GARMIN_EMAIL
├── GarminDailyStatsCache   — Garmin daily wellness payloads in SQLite (`calendar.db`) + their sync
├── StravaAnalytics         — Gathers each computation's inputs and caches the costly results
└── StravaVisualizer        — All matplotlib visualizations (heatmaps, dashboards, reports)
```

The rest of `zone2/`: `best_efforts.py` (records), `race_predictions.py`, `training_load.py` (TRIMP, fitness and form, relative effort) and `reports.py` (year in sport, weekly report) hold the maths `StravaAnalytics` calls; `drift.py` and `hr_recovery.py` the per-run HR summaries; `streams_store.py` the streams; `garmin_extractors.py` the slim Garmin projections; `map_matching.py`, `route_matching.py`, `city_coverage.py` (a city's persisted coverage, read without loading the city) and `route_planner.py` the coverage (see Map Matching); `paths.py` the data dir; `utils.py` units, sport categories and geo helpers.

### Data Flow

1. **Sync**: `StravaEndpoint` fetches activities from Strava API → `StravaActivitiesCache` stores them as yearly Parquet files under `{data_dir}/activities/{year}.parquet`
2. **Streams**: High-res GPS/HR data is fetched separately per-activity and stored by `StreamsStore` in yearly pickles (`{data_dir}/streams/{year}.pkl`, with a persisted id → year index). History-wide stats (records, race predictions, training load) never read raw streams: they use per-activity summaries (best efforts, HR sample counts) that `StreamsStore.summaries()` computes once per activity and persists in `summaries.pkl`
3. **Analysis**: `StravaAnalytics` reads from the cache and computes aggregated stats (returns plain dicts keyed by `StrEnum` feature classes: `YearInSportFeatures`, `AllYearInSportFeatures`, `WeeklyReportFeatures`)
4. **Visualization**: `StravaVisualizer` takes analytics output and generates PNG files in `{workdir}/` subdirectories
5. **Web API**: FastAPI backend (`backend/`) exposes analytics and cache data as REST endpoints consumed by the React frontend

### Web App (Frontend + Backend)

**Backend** (`backend/`): FastAPI app with 18 API routers at `/api/*`. Routers are thin (parameters, HTTP, background tasks) and never import each other; the logic lives in `backend/services/`, shared by the routers, the agent's tools and the sync loops, and services never import a router (`tests/test_structure.py` checks both). Services raise the domain errors in `backend/errors.py` (`NotFound`, `Invalid`, `Conflict`, `UpstreamUnavailable`, `UpstreamFailed`, all `ServiceError` with a message fit for the user): `app.py` answers each with its HTTP status (404, 400, 409, 503, 502) and the agent's tools turn them into a retry. Routers:
- `activities.py` — List, filter, sort activities; polylines for maps; similar activities
- `stats.py` — Weekly reports, year-in-sport, personal records, race predictions, relative effort, streaks
- `calendar.py` — Training session CRUD, scoring
- `exports.py` — PNG image generation (weekly reports, heatmaps, activity plots)
- `sync.py` — Background sync tasks, stream backfill, cache status
- `athlete.py` — Profile, rate limits, HR zones
- `gear.py` — Gear with activity rollups
- `goals.py` — Yearly goal CRUD with progress tracking
- `races.py` — Race calendar
- `garmin.py` — Garmin wellness (sleep, HRV, readiness, body battery), Garmin sync
- `coverage.py` / `plans.py` — City street coverage and planned exploration loops (see Map Matching)
- `calendar_feed.py` — Token-authed iCal feed of the calendar
- `agent.py` / `coach.py` — Coach chat (websocket), approvals and reviews; training plans, coach log and notes
- `routers/config.py` — Runtime settings for the browser; `health.py` — liveness probe
- `workouts.py` — Saved workouts (templates with segments). Saved run workouts are mirrored to the Garmin Connect library and sessions planned from them get Garmin calendar entries (`services/garmin_workouts.py`, reconciled after each Garmin sync); a structured session saved in the calendar links to the saved workout with the same steps or saves a new one (`services/workout_library.py`)
- `services/` — one module per concern: `sync` and `garmin_sync` (one sync at a time each, shared by the API, the auto-sync loops and the agent), `sessions`, `goals`, `races` and `workout_library` (each entity's single write path), `garmin_workouts` (the watch's workouts and calendar entries), `session_scores` (which activity fulfils a session, and its execution score from `scoring.py`), `plans` and `coach_log` (the coach), `training`, `briefing`, `activities`, `gear`, `zones` / `resting_hr`, `coverage` (cities and their download, map layers, held loops), `planned_routes` (planning loops, saved routes, sending them to Garmin) and `garmin_courses`, `day_timeline` / `activity_cost` (Garmin), `calendar_feed`, and the shared caches `stats_cache` and `export_cache`
- `dependencies.py` — DI providing `Zone2` singleton
- `config.py` — Pydantic settings (`STRAVA_WEB_*`: data dir, workdir, CORS origins, auto-sync intervals, coach model, CARTO key)
- `db.py` — SQLite via aiosqlite at `{data_dir}/calendar.db`: calendar and planning (`training_sessions`, `goals`, `workout_templates`, `race_events`, `planned_routes`, `garmin_workout_schedules`, `user_settings`), Garmin wellness (`garmin_daily_stats`, `garmin_daily_summary`) and the coach (`training_plans`, `plan_checkpoints`, `coach_log`, `agent_messages`, `agent_notes`, `agent_usage`, `agent_reviews`). The coach's conversation is `agent_messages`, a row per Pydantic AI message as JSON (`agent/message_store.py`, which imports nothing from Pydantic AI), so a turn only appends; the app keeps one conversation, and a message after a 30-minute pause opens a new session, the only part the model sees besides the notes and the coach log. `agent_conversations` holds the old one-JSON-per-conversation rows, already moved into `agent_messages`
- `agent/` — the z2 agent (Pydantic AI): one agent for every page that answers from your data and, with your approval, writes to it. `backend/agent/README.md` has the design, layout, build order and how to run it. Its tools call `backend/services/`, never routers; `python -m backend.agent call TOOL '{json}'` runs a tool without a model. The app imports nothing from Pydantic AI at startup (it costs ~60 MB on the Pi)

**Frontend** (`frontend/`): React 19 + TypeScript + Vite SPA:
- **Stack**: TailwindCSS 4, React Router 7, TanStack React Query, Recharts, Leaflet
- **Pages** (15): Calendar (home), Dashboard, Activities, ActivityDetail, Aggregations, Analytics, PersonalRecords, Races, Workouts, Coverage, Garmin, Coach, CoachPlan, GearDetail, Profile
- **Layout**: `AppShell` with dock navigation, dark/light theme support
- **API layer**: Axios client at `/api` (`api/client.ts`), React Query hooks by domain in `api/*.ts` (`activities`, `calendar`, `stats`, `goals`, `coach`…)
- **Dev**: Vite dev server on :5173 proxies `/api` to backend on :8000

**Deployment**: Multi-stage Dockerfile (Node 22 builds frontend → Python 3.12 serves via Uvicorn); docker-compose publishes the app on `127.0.0.1:8000` only (it has no auth of its own) behind Cloudflare Tunnel + Access; `scripts/auto-deploy.sh` (systemd timer in `deploy/`) redeploys the `prod` branch. See `DEPLOY.md`

### Map Matching (separate entry point)

`StravaMapMatcher` (`zone2/map_matching.py`) matches each activity to one continuous route with the route-based HMM in `zone2/route_matching.py` (Newson & Krumm style: candidates per GPS point, transitions scored by network route vs straight distance, outliers skipped instead of breaking the chain). It routes on a walkable network: streets (`{slug}_edges.parquet`, the network coverage is counted on) plus connectors such as sidewalks, crossings and steps (`{slug}_connectors.parquet`, never counted), both built straight from Overpass (via OSMnx's client, no OSMnx graph). Coverage is exactly what the routes walked: each activity's walked stretches (way row, from/to metres) are stored in `{slug}_walked.parquet`, stamped with the street map they index into (a state that doesn't match is re-matched by the next sync). The coverage map draws those stretches as run (connectors included, coloured by distinct runs); totals, districts, H3 hexes (resolution 8) and areas count the street metres walked, each once; the missing layer is the streets minus their walked stretches, served per viewport from `{slug}_viewport.parquet` without loading the city. Each activity's route is also stored in `{slug}_routes.parquet` and served at `/api/coverage/routes/{activity_id}` for the activity map. Input comes from `get_activities_as_gdf_from_streams()`; `match()` returns a `MatchResult` per activity. Every Strava sync ends with an incremental coverage sync of all cities (`sync_all_cities`); `pending_activities` checks what's new from the small state files, so nothing is loaded when there is nothing to match.

`ExplorationPlanner` (`zone2/route_planner.py`) plans runs from coverage: a loop of a given length from a start through optional via points, mostly over streets not run yet (or a chosen new/known share), avoiding chosen kinds of way (`WayClass`). It is an orienteering heuristic with scipy multi-source Dijkstra. `backend/services/planned_routes.py` plans loops (the coverage service holds each unsaved one until it is saved or its city deleted), keeps saved loops in the `planned_routes` table (with the network rows of their new streets, so the km still new update as coverage grows), and sends them to Garmin Connect as courses (`GarminClient.create_course` / `send_course`, the Connect web app's undocumented course endpoints), for the Coverage page (`backend/routers/plans.py`: `POST /api/coverage/{slug}/plan`, and `GET …/plan/{plan_id}` for a loop still held) and the coach's coverage tools alike. The coverage page's routes list also shows the user's Garmin courses in the city, map-matched for their km still new. The page opens on a city and a route from its URL (`/coverage?city={slug}&plan={plan_id}` or `&route={id}`), which is how the coach shows one.

### Key Conventions

- All geo data uses `EPSG:4326` (BASE_CRS) as base, projected to `EPSG:3857` (WEB_MERCATOR_CRS) for visualization
- Activity times: `start_date` (and `start_date_local`, parsed) is the local wall time labelled UTC, which every day/week bucket uses; `start_date_utc` is the true UTC start (Strava's `start_date`, tz-aware, null when no UTC offset is stored), for matching against real instants such as Garmin's
- Speed is stored in m/s (Strava API native); conversion to pace/speed uses `convert_speed()` / `format_pace_or_speed()` in `zone2/utils.py` which auto-detects sport category
- Sport categories: `SportCategory` in `zone2/utils.py` (running, walking, cycling, swimming, water, speed, other) from `get_sport_category(sport_type)`; walks and hikes are walking and never count as running. The app's sport filters (activities, dashboard, year in sport, goals) and planned sessions use an exact Strava sport type picked from a list; the agent's read tools filter by category
- Today and now: `z2.clock.today()` / `z2.clock.now()` (`zone2/clock.py`), the athlete's wall clock in the time zone of their latest activity (Strava's `timezone`), the server's own while none is known. `now()` is labelled UTC like `start_date_local`, so the two compare directly. Day, week and year buckets use it, not `date.today()` or UTC now (the Docker image runs in UTC)
- Visualizations use a consistent dark/neon aesthetic with configurable `neon_color` parameters
- Output images for reports use Instagram Story aspect ratio (9:16)
- Token/auth data cached in `{data_dir}/token.json`; activity metadata in `{data_dir}/metadata.json`
- `telegram_bot.py` uses `matplotlib.use("Agg")` for headless rendering and runs blocking Strava operations in a thread pool
- Frontend uses dark theme by default with custom surface color tokens and neon accents

### Files of Note

- `run_dev.py` — Runs backend + frontend dev servers concurrently
- `main.py` — Sandbox/example script, not a library entry point
