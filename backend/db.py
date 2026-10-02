import json
from pathlib import Path
from typing import Any

import aiosqlite
from fastapi import HTTPException

DB_PATH = Path(".strava/calendar.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    title TEXT NOT NULL,
    sport_type TEXT NOT NULL,
    description TEXT,
    planned_distance_km REAL,
    planned_duration_mins REAL,
    planned_intensity TEXT,
    target_pace_min REAL,
    target_pace_max REAL,
    target_hr_zone INTEGER,
    target_zone_pct REAL,
    segments TEXT,
    workout_template_id INTEGER,
    completed BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    sport_type TEXT NOT NULL,
    metric TEXT NOT NULL,
    period TEXT NOT NULL,
    target_value REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workout_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sport_type TEXT NOT NULL,
    description TEXT,
    segments TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS race_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    sport_type TEXT NOT NULL,
    distance_km REAL,
    target_pace REAL,
    description TEXT,
    location TEXT,
    url TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Loops saved from the coverage planner (see backend/routers/plans.py)
CREATE TABLE IF NOT EXISTS planned_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    distance_km REAL NOT NULL,
    new_km REAL NOT NULL,          -- when planned
    coordinates TEXT NOT NULL,     -- JSON [[lon, lat], ...] in running order
    new_ways TEXT NOT NULL,        -- JSON [[network row, metres], ...] of its new streets when planned
    network TEXT NOT NULL,         -- the street map those rows index into
    request TEXT NOT NULL,         -- JSON of the plan request (start, via, share, avoid, seed)
    garmin_course_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_planned_routes_slug ON planned_routes(slug);

CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS garmin_daily_stats (
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    payload TEXT NOT NULL,  -- zlib-compressed JSON (a BLOB), see zone2/garmin_cache.py
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (date, metric)
);
CREATE INDEX IF NOT EXISTS idx_garmin_date ON garmin_daily_stats(date);
CREATE INDEX IF NOT EXISTS idx_garmin_metric_date ON garmin_daily_stats(metric, date);
-- Covers the /garmin/status aggregates, which would otherwise read every payload.
CREATE INDEX IF NOT EXISTS idx_garmin_date_fetched ON garmin_daily_stats(date, fetched_at);

-- Slim per-day chart projections derived from garmin_daily_stats payloads at
-- sync time, so /trends reads a few hundred bytes/day instead of deserializing
-- the full payloads (a year of `sleep` alone is ~95MB of JSON).
CREATE TABLE IF NOT EXISTS garmin_daily_summary (
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (date, metric)
);
CREATE INDEX IF NOT EXISTS idx_garmin_summary_metric_date ON garmin_daily_summary(metric, date);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL (persisted file property, set once here) lets readers run
        # concurrently with the long Garmin backfill's writes; busy_timeout
        # makes contention wait rather than raise "database is locked".
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(_SCHEMA)
        # Migration: add scoring target columns to training_sessions
        cursor = await db.execute("PRAGMA table_info(training_sessions)")
        ts_columns = {row[1] for row in await cursor.fetchall()}
        for col, col_type in [
            ("target_pace_min", "REAL"),
            ("target_pace_max", "REAL"),
            ("target_avg_pace", "REAL"),
            ("target_hr_zone", "INTEGER"),
            ("target_zone_pct", "REAL"),
            ("segments", "TEXT"),
            ("workout_template_id", "INTEGER"),
        ]:
            if col not in ts_columns:
                await db.execute(f"ALTER TABLE training_sessions ADD COLUMN {col} {col_type}")
        await db.commit()

        # Migration: add year column if goals table existed without it
        cursor = await db.execute("PRAGMA table_info(goals)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "year" not in columns:
            await db.execute("DROP TABLE goals")
            await db.execute("""
                CREATE TABLE goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    sport_type TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    period TEXT NOT NULL,
                    target_value REAL NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await db.commit()


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # busy_timeout is per-connection — wait out a backfill's brief write
        # locks instead of erroring (WAL is already on from init_db).
        await db.execute("PRAGMA busy_timeout=5000")
        yield db


# ── Row helpers shared by the CRUD routers ──────────────────────────────
# Table and column names come from the routers' own models, never from requests.

def row_dict(row: aiosqlite.Row, json_cols: tuple[str, ...] = (), bool_cols: tuple[str, ...] = ()) -> dict:
    """A row as a dict, with JSON-text columns decoded (None when empty or
    unreadable) and SQLite 0/1 columns as booleans."""
    d = dict(row)
    for col in json_cols:
        d[col] = _decode_json(d.get(col))
    for col in bool_cols:
        d[col] = bool(d.get(col))
    return d


def _decode_json(raw: Any) -> Any:
    if not raw or not isinstance(raw, str):
        return raw or None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _encode(values: dict, json_cols: tuple[str, ...]) -> dict:
    return {k: json.dumps(v) if k in json_cols and v is not None else v for k, v in values.items()}


async def insert_row(db: aiosqlite.Connection, table: str, values: dict,
                     json_cols: tuple[str, ...] = ()) -> aiosqlite.Row:
    values = _encode(values, json_cols)
    cursor = await db.execute(
        f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join('?' * len(values))}) RETURNING *",
        tuple(values.values()),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row


async def update_row(db: aiosqlite.Connection, table: str, row_id: int, values: dict, not_found: str,
                     json_cols: tuple[str, ...] = ()) -> aiosqlite.Row:
    """Set `values` on row `row_id` and return it updated; 404 when it doesn't exist."""
    if not values:
        raise HTTPException(status_code=400, detail="No fields to update")
    values = _encode(values, json_cols)
    cursor = await db.execute(
        f"UPDATE {table} SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ? RETURNING *",
        (*values.values(), row_id),
    )
    row = await cursor.fetchone()
    await db.commit()
    if row is None:
        raise HTTPException(status_code=404, detail=not_found)
    return row


async def delete_row(db: aiosqlite.Connection, table: str, row_id: int, not_found: str) -> None:
    cursor = await db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail=not_found)
