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
    completed BOOLEAN DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)


async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
