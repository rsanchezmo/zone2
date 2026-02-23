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

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    sport_type TEXT NOT NULL,
    metric TEXT NOT NULL,
    period TEXT NOT NULL,
    target_value REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
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
