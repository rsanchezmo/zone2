# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Strava Intelligence is a Python toolkit for analyzing and visualizing Strava activities locally, without Strava Premium. It syncs activities via the Strava API, caches them as Parquet files, and generates neon-styled visualizations (heatmaps, dashboards, weekly/yearly reports) and map-matched street coverage maps.

## Setup & Running

```bash
# Install dependencies (Poetry required, Python 3.12+)
poetry install

# Run the main script (example usage / sandbox)
python main.py

# Run the Telegram bot (requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)
python telegram_bot.py
```

**Environment variables** (`.env` file in project root):
- `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` — required for API access
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — optional, for the Telegram bot

There are no tests, linter, or CI configured.

## Architecture

### Core Class Hierarchy

`StravaIntelligence` is the main orchestrator that wires everything together:

```
StravaIntelligence
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

### Map Matching (separate entry point)

`StravaMapMatcher` uses OSMnx + LeuvenMapMatching to match GPS tracks to OSM road networks. It operates on GeoDataFrames built from streams via `get_activities_as_gdf_from_streams()`. Returns `MatchResult` dataclass per activity.

### Key Conventions

- All geo data uses `EPSG:4326` (BASE_CRS) as base, projected to `EPSG:3857` (WEB_MERCATOR_CRS) for visualization
- Speed is stored in m/s (Strava API native); conversion to pace/speed uses `convert_speed()` / `format_pace_or_speed()` in `strava_utils.py` which auto-detects sport category
- Sport categories are classified via string matching in `strava_utils.py`: running, cycling, swimming
- Visualizations use a consistent dark/neon aesthetic with configurable `neon_color` parameters
- Output images for reports use Instagram Story aspect ratio (9:16)
- Token/auth data cached in `.strava/token.json`; activity metadata in `.strava/metadata.json`
- `telegram_bot.py` uses `matplotlib.use("Agg")` for headless rendering and runs blocking Strava operations in a thread pool

### Files of Note

- `strava/strava_intelligence_mcp.py` — Placeholder for future MCP server integration (currently empty)
- `main.py` — Sandbox/example script, not a library entry point
- `cache/` — SHA-based JSON cache files (for user data caching via `StravaUserCache`)
