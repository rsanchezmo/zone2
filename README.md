# z2

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

z2 is a training app I built around my own needs. What turned out to be most useful is having everything in one place: planning the week, digging through my data, and seeing on a map where I've run.

It syncs your activities from Strava, and optionally sleep, HRV and other watch data from Garmin Connect, and keeps it all on your own machine. It's built for running first, but rides, swims and everything else sync and show up too.

## What's in it

The **calendar** is where I start the day. I plan sessions there, and structured runs go straight to my Garmin watch as workouts. A morning briefing at the top puts today's session next to how recovered I am (sleep, HRV and readiness from Garmin) and says whether to go ahead, take it easy or rest. Races, goals and weekly totals live there too, and an iCal feed puts the plan in my phone's calendar.

Each **activity** has the usual splits, charts and segments, plus the things I wanted to see for myself: how much my heart rate drifted, how fast it came down after each rep, how the run compares to earlier ones on the same route, and how well I executed the session I had planned.

**Analytics** predicts race times from my recent best efforts, tracks fitness and form from training load, and estimates how much I slow down as the distance grows. Next to it are a year in sport page, all-time records, a map of every route, and pages for races, saved workouts, goals and gear (with a heads-up when a pair of shoes is near the end of its life). The weekly report, the year in sport, single activities and a route heatmap also export as neon PNG cards for sharing.

**Coverage** downloads a city's streets from OpenStreetMap, matches every run to them and shows how much of the city I've run, district by district. A route planner then builds a loop of the length I ask for, with the share of new streets I choose, staying off the kinds of way I want to avoid, and sends it to the watch as a course.

The **Garmin** page collects the wellness data Strava doesn't have: sleep, HRV, training readiness, body battery, stress, steps and a timeline of the day.

The **Coach** is an AI agent with a chat on every page. You can type, or hold the mic and dictate. It answers from your whole history, builds training plans with checkpoints, keeps notes of what you agree on, answers about your street coverage and plans loops (or sets up a new city) when you ask, and after each sync reviews the activities that fulfilled a session you planned. It never changes anything on its own: each change it proposes comes as a card you approve or turn down. The conversation lives on the server, so you can start it on the laptop and carry on from the phone, and the robot shows a badge for replies and reviews you haven't read yet. It uses OpenAI models through Pydantic AI, or a local model through Ollama. [`backend/agent/README.md`](backend/agent/README.md) explains how it works.

## What you need

- **A Strava subscription.** Strava's API now requires one. Their [getting started guide](https://developers.strava.com/docs/getting-started/) says "A Strava subscription is a prerequisite for creating an app", and apps that already existed on the Standard tier needed one from 30 June 2026.
- Python 3.12+ with [Poetry](https://python-poetry.org/), and Node 22 for the frontend.
- Optional: a Garmin Connect account, an OpenAI API key for the Coach, and a Cloudflare Tunnel token if you want to reach it from outside your home.

## Running it

1. **Create a Strava app** in your [Strava API settings](https://www.strava.com/settings/api), with `localhost` as its Authorization Callback Domain (on a server, the domain you open z2 at).
2. **Install and start z2**, with the app's Client ID and Client Secret in `.env`:

   ```bash
   git clone https://github.com/rsanchezmo/zone2.git
   cd zone2
   poetry install
   (cd frontend && npm install)
   cp .env.example .env    # STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET
   poetry run python run_dev.py
   ```

3. **Connect your accounts in the app** at http://localhost:5173 (the API is on :8000):
   - **Strava:** click **Connect Strava** and approve z2 on Strava's page with both boxes ticked (z2 reads your private activities and the HR zones in your profile). Strava sends you back to the app, which starts pulling your history (see [The first sync](#the-first-sync)).
   - **Garmin** (optional, for sleep, HRV, readiness and the watch): click **Connect** under Garmin Connect on the Profile page and sign in, with the code Garmin sends if your account asks for one. The Garmin tab then appears in the dock, Garmin syncs every 6 hours, and Backfill all on that page fetches your whole history.

   z2 keeps only the sessions, in `.strava/token.json` and `.strava/garmin/`, never your passwords, and they refresh on their own.

The rest of `.env` is optional:

```env
OPENAI_API_KEY=                  # the Coach
STRAVA_WEB_CARTO_API_KEY=        # nicer basemaps (free key); maps fall back to OpenStreetMap without it
STRAVA_WEB_AUTO_SYNC_HOURS=12    # sync Strava every 12 h in the background; off when unset
CLOUDFLARE_TUNNEL_TOKEN=         # remote access with Docker
```

The other `STRAVA_WEB_*` settings, such as the Coach's model (`STRAVA_WEB_AGENT_MODEL`), are in [`backend/config.py`](backend/config.py). `GARMIN_EMAIL` and `GARMIN_PASSWORD` still work in place of connecting Garmin in the app.

Everything z2 keeps is in two folders: `.strava/` (activities, streams, tokens, and the SQLite database with the calendar, plans and workouts) and `zone2_workdir/` (street maps and exports), both in the checkout unless `STRAVA_WEB_DATA_DIR` and `STRAVA_WEB_WORKDIR` point elsewhere. Those are the folders to back up. The backend, the bot and the scripts read `.env` from the checkout, wherever you start them from.

### The first sync

Once Strava is connected, z2 pulls your whole history in two passes:

1. **Your activities.** The list comes 200 at a time, so even years of runs are in the calendar, the activity list and the totals within a minute.
2. **Each activity's GPS, heart rate, splits and photos.** Strava allows an app 100 reads every 15 minutes and 1,000 a day, and each activity takes two or three, so that's 40 to 50 activities per window and up to about 450 a day. When the limit stops the sync, z2 saves what it has and carries on by itself when Strava's window resets: every quarter hour, or after midnight UTC once the day's requests are used. The sync menu shows when it carries on next.

A history of 2,000 activities takes four to six days to fill in, with nothing to click. Records, race predictions, fitness, coverage maps and HR drift fill in as the streams arrive. New activities afterwards sync in seconds.

## Running it on a home server

```bash
docker compose up -d --build        # the app on 127.0.0.1:8000, plus the Cloudflare Tunnel
docker compose up -d --build app    # just the app
```

The app has no login of its own, so it only listens on the server's loopback and Cloudflare Access guards the way in. Set your Strava app's callback domain to the domain you reach it at, and connect Strava and Garmin from the app as you would locally, with no files to copy over. [DEPLOY.md](DEPLOY.md) walks through setting up Cloudflare Tunnel and Access, and an optional timer that redeploys when you push. Days and weeks follow the time zone of your latest activity, so a server running in UTC still rolls over at your midnight.

## Finding your way around

`zone2/` is the core library: the Strava and Garmin clients, the local cache, analytics, map matching and the route planner. `backend/` is the FastAPI app on top of it, with thin routers over `backend/services/`; `backend/agent/` is the Coach, `frontend/` is the React app and `tests/` the test suite. [CLAUDE.md](CLAUDE.md) has the architecture in more detail.

Two older pieces still work: `telegram_bot.py` posts the weekly report and year in sport cards to a Telegram chat (it needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`), and `main.py` is my scratchpad for using the `zone2` package straight from Python.

If you change things, run `./scripts/install-hooks.sh` once. Its pre-commit hook catches secrets like `.env` before they're committed. CI runs the frontend's `npm run lint` and build, ruff, the Python tests (`poetry run pytest -q`, synthetic data only) and the Docker build, so keep them all passing.

## Strava

z2 stores your Strava data locally. It's up to you to follow [Strava's API Agreement](https://www.strava.com/legal/api). z2 is an independent project, not affiliated with or endorsed by Strava.

## License

[MIT](LICENSE)
