# z2

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

z2 is a training app I built around my own needs. What turned out to be most useful is having everything in one place: planning the week, digging through my data, and seeing on a map where I've run.

It syncs your activities from Strava, and optionally sleep, HRV and other watch data from Garmin Connect, and keeps it all on your own machine. It's built for running first, but rides, swims and everything else sync and show up too.

## What's in it

The **calendar** is where I start the day. I plan sessions there, and structured runs go straight to my Garmin watch as workouts. A morning briefing at the top puts today's session next to how recovered I am (sleep, HRV and readiness from Garmin) and says whether to go ahead, take it easy or rest. Races, goals and weekly totals live there too, and an iCal feed puts the plan in my phone's calendar.

Each **activity** has the usual splits, charts and segments, plus the things I wanted to see for myself: how much my heart rate drifted, how fast it came down after each rep, how the run compares to earlier ones on the same route, and how well I executed the session I had planned.

**Analytics** predicts race times from my recent best efforts, tracks fitness and form from training load, and estimates how much I slow down as the distance grows. Next to it are a year in sport page, all-time records, a map of every route, and pages for races, saved workouts, goals and gear (with a heads-up when a pair of shoes is near the end of its life). The weekly report, the year in sport, single activities and a route heatmap also export as neon PNG cards for sharing.

**Coverage** downloads a city's streets from OpenStreetMap, matches every run to them and shows how much of the city I've run, district by district. A route planner then builds a loop of the length I ask for, mostly over streets I haven't run yet, and sends it to the watch as a course.

The **Garmin** page collects the wellness data Strava doesn't have: sleep, HRV, training readiness, body battery, stress, steps and a timeline of the day.

The **Coach** is an AI agent with a chat on every page. You can type, or hold the mic and dictate. It answers from your whole history, builds training plans with checkpoints, and after each sync reviews the activities that fulfilled a session you planned. It never changes anything on its own: each change it proposes comes as a card you approve or turn down. It uses OpenAI models through Pydantic AI, or a local model through Ollama. [`backend/agent/README.md`](backend/agent/README.md) explains how it works.

## What you need

- **A Strava subscription.** Strava's API now requires one. Their [getting started guide](https://developers.strava.com/docs/getting-started/) says "A Strava subscription is a prerequisite for creating an app", and apps that already existed on the Standard tier needed one from 30 June 2026.
- Python 3.12+ with [Poetry](https://python-poetry.org/), and Node 22 for the frontend.
- Optional: a Garmin Connect account, an OpenAI API key for the Coach, and a Cloudflare Tunnel token if you want to reach it from outside your home.

## Running it

Create an app in your [Strava API settings](https://www.strava.com/settings/api) and set its Authorization Callback Domain to `localhost`. Then:

```bash
git clone https://github.com/rsanchezmo/zone2.git
cd zone2
poetry install
(cd frontend && npm install)
cp .env.example .env    # then fill it in, see below
```

The first time, start the backend on its own, so the Strava login can ask you for a code in the terminal:

```bash
poetry run uvicorn backend.app:app --port 8000
```

It opens Strava in your browser. Approve the app, and Strava redirects you to a `localhost/exchange_token` page that won't load. Copy the `code` from its address and paste it into the terminal. The token is saved in `.strava/token.json` and refreshes on its own from then on. Stop the backend, and from now on run both servers together:

```bash
poetry run python run_dev.py
```

The app is at http://localhost:5173 and the API at http://localhost:8000. Hit Sync Now under the sync icon in the dock to pull your history. Strava's rate limits make the first sync of a long history slow, and Backfill Streams, in the same menu, picks up where the last one stopped.

The `.env` file:

```env
# Required
STRAVA_CLIENT_ID=
STRAVA_CLIENT_SECRET=

# Optional
GARMIN_EMAIL=                    # wellness data, watch workouts and courses
GARMIN_PASSWORD=
OPENAI_API_KEY=                  # the Coach
STRAVA_WEB_CARTO_API_KEY=        # nicer basemaps (free key); maps fall back to OpenStreetMap without it
STRAVA_WEB_AUTO_SYNC_HOURS=12    # sync Strava every 12 h in the background; off when unset
CLOUDFLARE_TUNNEL_TOKEN=         # remote access with Docker
```

The other `STRAVA_WEB_*` settings, such as the Coach's model (`STRAVA_WEB_AGENT_MODEL`), are in [`backend/config.py`](backend/config.py).

With Garmin credentials set, Garmin syncs every 6 hours, and Backfill all on the Garmin page fetches your whole history. If your account asks for a two-factor code, run `poetry run python scripts/garmin_poc.py` once in a terminal so the login gets cached in `.strava/garmin/`.

Everything z2 keeps is in two folders: `.strava/` (activities, streams, tokens, and the SQLite database with the calendar, plans and workouts) and `zone2_workdir/` (street maps and exports). Those are the folders to back up.

## Running it on a home server

```bash
docker compose up -d --build        # the app on 127.0.0.1:8000, plus the Cloudflare Tunnel
docker compose up -d --build app    # just the app
```

The app has no login of its own, so it only listens on the server's loopback and Cloudflare Access guards the way in. A container can't do the interactive Strava login either, so authorise once on your laptop and copy `.strava/` onto the server. [DEPLOY.md](DEPLOY.md) walks through that, setting up Cloudflare Tunnel and Access, and an optional timer that redeploys when you push.

## Finding your way around

`zone2/` is the core library: the Strava client, the local cache, analytics and map matching. `backend/` is the FastAPI app on top of it, `backend/agent/` is the Coach, and `frontend/` is the React app. [CLAUDE.md](CLAUDE.md) has the architecture in more detail.

Two older pieces still work: `telegram_bot.py` posts the weekly report and year in sport cards to a Telegram chat (it needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`), and `main.py` is my scratchpad for using the `zone2` package straight from Python.

If you change things, run `./scripts/install-hooks.sh` once. Its pre-commit hook catches secrets like `.env` before they're committed. CI runs `npm run lint` and the frontend build, so keep both at zero errors.

## Strava

z2 stores your Strava data locally. It's up to you to follow [Strava's API Agreement](https://www.strava.com/legal/api). z2 is an independent project, not affiliated with or endorsed by Strava.

## License

[MIT](LICENSE)
