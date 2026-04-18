import aiosqlite
from pathlib import Path

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

CREATE TABLE IF NOT EXISTS user_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
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
        yield db
