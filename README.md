# 🏃 Strava Intelligence

A Python toolkit for analyzing and visualizing your Strava activities without paying for Strava Premium. Sync your activities, generate cool visualizations, and track your performance metrics over time. This repository is conceived as a starting point for building more advanced Strava data analysis tools. I will keep adding features and visualizations over time.

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)

> ⚠️ **Disclaimer**: This project stores Strava data locally on your machine. It is the responsibility of each user to comply with [Strava's API Agreement](https://www.strava.com/legal/api) and their terms regarding data storage and usage. Please review Strava's policies before using this tool.

## ✨ Current features

- **Web Dashboard**: Full-featured React frontend with FastAPI backend:
  - 📅 **Calendar**: Monthly calendar with activity overlay, training session planning, weekly report, goal progress, streaks, and race countdowns
  - 🏃 **Activities**: Browsable activity list with detail views, stream charts, splits, segments, and map visualization
  - 🌍 **Aggregations**: Interactive Leaflet map with all your routes, filterable by sport and year, plus heatmap export
  - ⚡ **Dashboard**: Yearly stats with goal ring, monthly charts, records, and sport breakdowns
  - 🏆 **Personal Records**: Best efforts at standard distances with sport-category totals
  - 🏋️ **Workouts**: Structured workout templates with segments (warmup / work / recovery / cooldown)
  - ⚑ **Races**: Race calendar with day-countdowns, past-race activity linking, and notes
  - 👤 **Profile**: Athlete profile, HR zones, goals management, cache completeness, and API rate limits
  - 📸 **PNG Exports**: Preview-first export dialog for every visualization (quality, color, filename)
  - 🌗 **Dark/Light Mode**: Full theme toggle with persistent preference
- **Activity Sync**: Automatically sync and cache your Strava activities locally using Parquet files
- **Cool Visualizations**: Generate visualizations including:
  - ⚡ **Thunderstorm Heatmap**: Neon-style activity route visualization on dark backgrounds
  - 🕐 **Activity Clock**: Polar scatter plot showing when you train (time vs distance)
  - 🎛️ **HUD Dashboard**: Cyberpunk-style histograms for distance, heart rate, and pace
  - 📈 **Efficiency Factor**: Track your aerobic efficiency (speed/HR) over time
  - 🚀 **Performance Frontier**: Pareto frontier with Riegel's fatigue model fitting
  - 📅 **Weekly Report**: Instagram Story-sized weekly training summary with HR zones, sports breakdown, and accumulated training time
  - 🎯 **Year in Sport**: Instagram Story-sized summaries of your yearly training (main sport & totals)
  - 🏆 **Activity Plots**: Neon-style individual activity visualization with elevation profile
- **Map Matching**: Match GPS tracks to OpenStreetMap road networks using HMM-based matching:
  - 🗺️ **Street Coverage Map**: Neon-glow visualization of all streets you've traversed in a city
  - 📍 **Activity Match Plot**: Per-activity visualization showing GPS track, matched OSM edges, and snap points
  - 📊 **Coverage Stats**: Track how many km of a city's street network you've covered
- **Analytics**: WIP
- **GeoJSON Export**: Export your activities as GeoJSON for use in mapping applications such as QGIS
- **Telegram Bot**: Automated scheduled delivery of weekly and monthly reports to your Telegram chat
- **Smart Caching**: Efficient local caching with incremental sync support to avoid redundant API calls

## 📋 Prerequisites

- Python 3.12+
- A Strava FREE account with API access
- Strava API credentials (Client ID and Client Secret)

## 🔧 Installation

### Using Poetry (Recommended)

```bash
# Clone the repository
git clone https://github.com/rsanchezmo/strava-intelligence.git
cd strava-intelligence

# Install dependencies with Poetry
poetry install

# Activate the virtual environment
poetry env activate
```

### Using pip

```bash
# Clone the repository
git clone https://github.com/rsanchezmo/strava-intelligence.git
cd strava-intelligence

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install -e .
```

## 🔑 Strava API Setup

1. Go to [Strava API Settings](https://www.strava.com/settings/api)
2. Create a new application to get your **Client ID** and **Client Secret**
3. Create a `.env` file in the project root:

```env
STRAVA_CLIENT_ID=your_client_id
STRAVA_CLIENT_SECRET=your_client_secret
```

4. On first run, the app will open a browser for OAuth authorization. Follow the prompts to grant access.

## 🤖 Telegram Bot Setup (Optional)

You can optionally set up a Telegram bot to receive automated weekly reports (Sundays at 21:00) and monthly Year in Sport summaries (last day of month at 21:00).

1. Create a Telegram bot via [@BotFather](https://t.me/botfather) and get your bot token
2. Get your Telegram chat ID (send a message to your bot, then visit `https://api.telegram.org/bot<YourBOTToken>/getUpdates`)
3. Add these to your `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

4. Run the bot:

```bash
python telegram_bot.py
```

The bot supports manual commands:
- `/weekly` - Generate and send current week's report
- `/monthly` - Generate and send current year's report

## 🌐 Web Dashboard

Run the full web app (FastAPI backend + React frontend):

```bash
# Install dependencies
poetry install
cd frontend && npm install && cd ..

# Run both backend and frontend in development mode
python run_dev.py
```

The app will be available at `http://localhost:5173`. The backend API runs on `http://localhost:8000`.

### Production deployment

To run the web app on a home server (Raspberry Pi, small VPS, etc.) behind a Cloudflare Tunnel with Cloudflare Access authentication, see **[DEPLOY.md](./DEPLOY.md)**. It covers:

- Cloudflare Tunnel + Access setup
- Docker Compose on ARM64
- Seeding the activity cache to skip the interactive OAuth on a headless box
- SSH over the same tunnel
- Automated redeploys on push via a systemd timer (see [`deploy/README.md`](./deploy/README.md))

## 🚀 Quick Start (Python API)

```python
from strava.strava_intelligence import StravaIntelligence
from pathlib import Path

# Initialize (auto-syncs activities if cache is older than 12 hours)
strava = StravaIntelligence(workdir=Path("./strava_intelligence_workdir"))

# Generate a thunderstorm heatmap for your runs in a city
strava.strava_visualizer.thunderstorm_heatmap(
    sport_types=['Run'],
    location="paris",
    radius_km=20.0,
    add_basemap=False
)

# Create an activity clock visualization
strava.strava_visualizer.activity_clock(sport_types=['Run'])

# Generate a HUD-style dashboard
strava.strava_visualizer.hud_dashboard(sport_types=['Run'])

# Plot efficiency factor trend
strava.strava_visualizer.plot_efficiency_factor(sport_types=['Run'])

# Plot performance frontier with fatigue model
strava.strava_visualizer.plot_performance_frontier(sport_types=['Run'])

# Generate Year in Sport summary (Instagram Story format)
strava.get_year_in_sport(year=2025, main_sport="Run", neon_color="#fc0101")

# Generate Year in Sport with comparison to previous year
strava.get_year_in_sport(
    year=2025, 
    main_sport="Run", 
    neon_color="#fc0101",
    comparison_year=2024,
    comparison_neon_color="#00aaff"
)

# Generate Weekly Report (Instagram Story format)
strava.get_weekly_report(week_start_date="2026-01-12", neon_color="#fc0101")

# Export activities as GeoJSON
strava.save_geojson_activities()

# --- Map Matching & Street Coverage ---
from strava.strava_map_matching import StravaMapMatcher
from strava.strava_utils import get_activities_as_gdf_from_streams

# Initialize the map matcher for a city
map_matcher = StravaMapMatcher(
    city_name="Paris, France",
    workdir=Path("./strava_intelligence_workdir"),
    force_reload=False,
)

# Build a GeoDataFrame from high-res GPS streams
activities_gdf = get_activities_as_gdf_from_streams(
    strava.strava_activities_cache.activities
)

# Match all activities to the OSM road network
matched_gdf, match_details = map_matcher.match(activities_gdf)

# Plot individual activity match results
for activity_id, result in match_details.items():
    result.plot(save_path=f"map_match_{activity_id}.png")

# Generate a city-wide street coverage map
map_matcher.plot_coverage(match_details, save_path="coverage.png")
```

## 📊 Visualizations

### Thunderstorm Heatmap
A stunning neon visualization of your activity routes on a dark canvas. Perfect for showcasing your training coverage in a specific area.

| Thunderstorm Heatmap | Activity Clock |
|:---:|:---:|
| ![Thunderstorm Heatmap](readme_data/thunderstorm_run.png) | ![Activity Clock](readme_data/activity_clock_run.png) |
| Neon-style route visualization on dark backgrounds | Polar plot showing training patterns by time of day |

### HUD Dashboard & Analytics

| HUD Dashboard | Efficiency Factor | Performance Frontier |
|:---:|:---:|:---:|
| ![HUD Dashboard](readme_data/hud_run.png) | ![Efficiency Factor](readme_data/efficiency_factor.png) | ![Performance Frontier](readme_data/performance_frontier.png) |
| Distance, HR & Pace distributions | Aerobic efficiency over time | Best performances with Riegel's model |

### Weekly Report & Bubble Map

| Weekly Report | Bubble Map |
|:---:|:---:|
| ![Weekly Report](readme_data/weekly_report_2026-01-12.png) | ![Bubble Map](readme_data/bubble_map_country.png) |
| Instagram Story-sized weekly summary with HR zones, sport breakdowns, and training progression | Geographic bubble visualization of activity locations |

### Year in Sport
Generate Instagram Story-sized (9:16) summaries of your yearly training with optional **year comparison**.

| Main Sport | All Sports | Activity Plot |
|:---:|:---:|:---:|
| ![Year in Sport - Main](readme_data/year_in_sport_2025_run.png) | ![Year in Sport - Totals](readme_data/year_in_sport_2025_totals.png) | ![Year in Sport - Activity](readme_data/year_in_sport_activity.png) |
| Stats, monthly chart & personal bests | Aggregated stats across all sports | Route map with elevation profile |

| Year Comparison — Run | Year Comparison — Totals |
|:---:|:---:|
| ![Comparison Run](readme_data/year_in_sport_2025_run_comparison.png) | ![Comparison Totals](readme_data/year_in_sport_2025_totals_comparison.png) |
| Side-by-side stats with grouped bar charts | Cross-sport comparison with highlighted differences |

### Map Matching & Street Coverage
Match your Strava activities to the OpenStreetMap road network using HMM-based map matching.

| Street Coverage Map | Activity Match Plot |
|:---:|:---:|
| ![Street Coverage Map](readme_data/coverage.png) | ![Activity Match Plot](readme_data/map_match_example.png) |
| Traversed streets glow in neon against the dim untraversed network | GPS track (red), matched OSM edges (blue), snap connections (white) |

### QGIS GeoJSON Export
Export your activities as GeoJSON for advanced spatial analysis in QGIS.

| All Activities | Activity Info |
|:---:|:---:|
| ![QGIS All Activities](readme_data/qgis_all.png) | ![QGIS Activity Info](readme_data/qgis_info.png) |

## 🏗️ Project Structure

```
strava-intelligence/
├── main.py                         # Example usage (Python API)
├── telegram_bot.py                 # Scheduled Telegram reports
├── run_dev.py                      # Dev launcher (backend + frontend)
├── pyproject.toml                  # Poetry configuration
├── Dockerfile                      # Multi-stage build (Node → Python)
├── docker-compose.yml              # App + Cloudflare Tunnel
├── README.md
├── DEPLOY.md                       # Raspberry Pi / production guide
├── backend/                        # FastAPI backend
│   ├── app.py                      # FastAPI application + lifespan
│   ├── config.py                   # Pydantic settings
│   ├── db.py                       # SQLite (calendar / goals / workouts)
│   ├── dependencies.py             # DI for the StravaIntelligence singleton
│   ├── export_cache.py             # In-memory TTL cache for PNG exports
│   ├── scoring.py                  # Session execution scoring
│   ├── _serialize.py               # numpy/pandas → JSON sanitizer
│   ├── _ttl_cache.py               # Thread-safe TTL cache primitive
│   └── routers/                    # API route handlers
│       ├── activities.py
│       ├── athlete.py
│       ├── calendar.py
│       ├── exports.py
│       ├── goals.py
│       ├── health.py
│       ├── races.py
│       ├── stats.py
│       ├── sync.py
│       └── workouts.py
├── frontend/                       # React + Vite (TypeScript) SPA
│   ├── src/
│   │   ├── App.tsx                 # Routes + lazy pages + ErrorBoundary
│   │   ├── main.tsx                # Entry point + QueryClient defaults
│   │   ├── index.css               # Tailwind v4 tokens + primitives
│   │   ├── api/                    # Axios client + React Query hooks
│   │   ├── components/
│   │   │   ├── icons.tsx           # Inline SVG icon set
│   │   │   ├── layout/             # AppShell, RootErrorBoundary
│   │   │   └── shared/             # ChartPanel, GoalRing, StatCard, …
│   │   ├── hooks/                  # Theme + toast
│   │   └── pages/                  # Dashboard, Calendar, Activities, …
│   └── vite.config.ts
├── deploy/                         # systemd units for auto-deploy
│   ├── strava-deploy.service
│   ├── strava-deploy.timer
│   └── README.md
├── scripts/                        # Deploy + dev scripts
│   ├── auto-deploy.sh              # prod-branch poller (run by systemd)
│   ├── install-hooks.sh            # one-shot git hooks installer
│   └── hooks/pre-commit            # secret-scanning pre-commit hook
└── strava/                         # Core Python library
    ├── constants.py                # CRS constants
    ├── strava_activities_cache.py  # Parquet-backed cache w/ cache_version
    ├── strava_analytics.py         # Year-in-sport, weekly report, PRs, PMC
    ├── strava_endpoint.py          # Strava API client w/ rate-limit pre-check
    ├── strava_intelligence.py      # Main orchestrator class
    ├── strava_map_matching.py      # OSM map matching & coverage
    ├── strava_user_cache.py        # User data caching
    ├── strava_utils.py             # Utility functions
    └── strava_visualizer.py        # Visualization generators
```

## 📝 API Reference

The library is organized around one orchestrator (`StravaIntelligence`) that
wires together four focused components. All Python methods listed below are
the public surface; the web API exposes the same functionality via
`/api/*` routes (see `backend/routers/`).

### StravaIntelligence

The main class that orchestrates all functionality.

```python
StravaIntelligence(
    workdir: Path,                  # Working directory for generated outputs
    auto_sync: bool = True,         # Auto-sync on initialization
    sync_max_age_hours: int = 12,   # Cache age threshold for auto-sync
)
```

**Methods:**
- `sync_activities(full_sync=False, include_streams=False)` — pull new activities from Strava
- `ensure_activities_with_streams()` — backfill streams / photos / detail for cached activities
- `save_geojson_activities()` / `save_gpkg_activities()` — export the full cache to GeoJSON or GeoPackage
- `plot_last_activity(sport_type)` — render the most recent activity of the given sport
- `get_year_in_sport(year, main_sport, neon_color, comparison_year=None, comparison_neon_color="#00aaff")` — Year-in-Sport visualizations with optional year comparison
- `get_weekly_report(week_start_date=None, neon_color="#fc0101")` — weekly training summary (current week by default)

### StravaVisualizer

Generates all matplotlib visualizations. Every rendering method supports
`return_buffer=True` (returns a PNG `BytesIO` — used by the web `/api/exports`
endpoints) and `dpi=<int>` (override quality).

**Methods:**
- `thunderstorm_heatmap(location, sport_types, radius_km, neon_color, show_title, year, return_buffer, dpi)` — neon route overlay
- `activity_bubble_map(region, sport_types, min_radius_scale, grid_density, neon_color, show_title, return_buffer, dpi)` — bubble aggregation per grid cell
- `activity_clock(sport_types, neon_color, return_buffer, dpi)` — polar plot (time-of-day × distance)
- `plot_activity(activity_id, strava_endpoint, folder, title, neon_color, return_buffer, dpi)` — single-activity neon plot
- `plot_year_in_sport_main(year, year_in_sport, main_sport, folder, neon_color, comparison_year, comparison_data, comparison_neon_color, return_buffer, dpi)`
- `plot_year_in_sport_totals(year, year_in_sport, folder, neon_color, comparison_year, comparison_data, comparison_neon_color, return_buffer, dpi)`
- `hud_dashboard(sport_type, neon_color, return_buffer, dpi)` — cyberpunk histograms
- `plot_efficiency_factor(sport_type, window=14, return_buffer, dpi)` — aerobic efficiency over time
- `plot_performance_frontier(sport_types, return_buffer, dpi)` — Pareto frontier + Riegel fit
- `plot_weekly_report(weekly_report, folder, neon_color, last_week_report, return_buffer, dpi)` — Instagram-Story sized weekly summary

### StravaAnalytics

Pure-Python analytics over the activity cache. All methods are memoized and
invalidate on sync via a `cache_version` token.

**Methods:**
- `get_weekly_report(week_start_date=None, cutoff_date=None)` — weekly totals, HR zones, sport breakdown
- `get_year_in_sport(year, main_sport, cutoff_month_day=None)` — yearly aggregates for one sport
- `get_all_year_in_sport(year, cutoff_month_day=None)` — cross-sport yearly aggregates
- `get_personal_records()` — best efforts at standard distances per sport category
- `get_race_predictions(sport_category="running")` — VDOT/Riegel-based predicted race times
- `get_daily_training_load()` — per-day TRIMP (zone-weighted when streams available, Banister fallback)
- `get_pmc_chart(start_date=None, end_date=None)` — Performance Management Chart (CTL / ATL / TSB)
- `get_fitness_trend(sport_type="Run", start_date=None, end_date=None)` — VDOT trend with rolling average
- `get_hr_zones()` / `get_max_heart_rate()` / `get_rest_heart_rate()` — HR zone configuration
- `get_current_vo2_max()` — VO₂max estimate from recent efforts
- `invalidate_caches()` — clear all memoized analytics (called on sync)

### StravaMapMatcher

HMM-based map matching of GPS tracks to OSM road networks.

```python
StravaMapMatcher(
    city_name: str,              # City name for OSM network download
    workdir: Path,               # Working directory for cached maps
    force_reload: bool = False,  # Force re-download of OSM data
)
```

**Methods:**
- `match(activities)` — map-match a GeoDataFrame of activities; returns matched GeoDataFrame + per-activity `MatchResult` dict
- `coverage_stats(match_results)` — city-wide coverage (km traversed, % covered, unique roads)
- `plot_coverage(match_results, save_path, neon_color, figsize)` — neon-glow coverage map

## 🗺️ Roadmap

- [x] Telegram bot for automated weekly and monthly reports
- [x] Web dashboard with React frontend and FastAPI backend
- [x] Dark/light mode support
- [x] Athlete profile page with HR zones
- [ ] Extend the analytics, use ML models to provide deeper insights, such as training load, fatigue estimation, and performance prediction
- [ ] Add more visualizations
- [ ] Create an mcp server to expose Strava data so you can access it from your LLM based agents

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

After cloning, install the local git hooks once so the pre-commit check can
catch accidentally-staged secrets (`.env`, tokens, etc.) before they reach
GitHub:

```bash
./scripts/install-hooks.sh
```

Hooks live in `scripts/hooks/` (version-controlled) and are symlinked into
your local `.git/hooks/` — edit once, they update everywhere.
