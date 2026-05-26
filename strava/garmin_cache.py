"""SQLite-backed cache for Garmin daily wellness payloads + sync orchestration.

The cache stores one row per (date, metric) holding the raw JSON payload from
`garminconnect`. Charts pluck fields from the payload at read time — keeping
the schema generic means new fields from Garmin firmware updates appear
without migrations.

Why plain `sqlite3` (not aiosqlite)?
- The sync worker runs in a thread pool (FastAPI BackgroundTasks with a sync
  function), where aiosqlite buys nothing.
- All Strava routers in this codebase are sync handlers, so sync DB access
  matches the surrounding style.
- The DB is small and writes are infrequent; a fresh connection per call is
  cheap and avoids any cross-thread connection-sharing footguns.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import date as date_t, datetime, timedelta
from pathlib import Path
from typing import Any

from strava.garmin_client import GarminClient

logger = logging.getLogger(__name__)

DB_PATH = Path(".strava/calendar.db")

# Use `sleep` as the "did the watch capture data?" canary during backfill.
# Older days where the user didn't own the watch return null sleep payloads.
_EMPTY_STREAK_TO_STOP = 21
_PER_CALL_DELAY_S = 0.3       # be polite to Garmin between API calls
_RANGE_CHUNK_DAYS = 90        # range fetches (body_battery, steps) walk in chunks


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


class GarminDailyStatsCache:
    """CRUD + sync orchestration over the `garmin_daily_stats` table."""

    def __init__(self, client: GarminClient):
        self.client = client
        # Single sync worker at a time (writes interleave fine but the
        # garminconnect HTTP session isn't safe to hammer concurrently).
        self._sync_lock = threading.Lock()

    # ---------------------------------------------------------------- writes

    def upsert(self, d: date_t | str, metric: str, payload: Any) -> None:
        if payload is None:
            return  # don't store nulls — leaves a "missing" gap we can refetch
        iso = d if isinstance(d, str) else d.isoformat()
        blob = json.dumps(payload, default=str)
        with _conn() as c:
            c.execute(
                """INSERT INTO garmin_daily_stats (date, metric, payload, fetched_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(date, metric) DO UPDATE SET
                     payload = excluded.payload,
                     fetched_at = excluded.fetched_at""",
                (iso, metric, blob),
            )

    def upsert_many(self, rows: list[tuple[str, str, Any]]) -> None:
        """rows = [(date_iso, metric, payload_dict_or_list), ...]"""
        items = [(d, m, json.dumps(p, default=str)) for d, m, p in rows if p is not None]
        if not items:
            return
        with _conn() as c:
            c.executemany(
                """INSERT INTO garmin_daily_stats (date, metric, payload, fetched_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(date, metric) DO UPDATE SET
                     payload = excluded.payload,
                     fetched_at = excluded.fetched_at""",
                items,
            )

    # ---------------------------------------------------------------- reads

    def get(self, d: date_t | str, metric: str) -> Any | None:
        iso = d if isinstance(d, str) else d.isoformat()
        with _conn() as c:
            row = c.execute(
                "SELECT payload FROM garmin_daily_stats WHERE date = ? AND metric = ?",
                (iso, metric),
            ).fetchone()
            return json.loads(row["payload"]) if row else None

    def get_range(self, metric: str, start: date_t | str, end: date_t | str) -> list[dict]:
        """Returns list of {date, payload} ordered by date ascending."""
        s = start if isinstance(start, str) else start.isoformat()
        e = end if isinstance(end, str) else end.isoformat()
        with _conn() as c:
            rows = c.execute(
                """SELECT date, payload FROM garmin_daily_stats
                   WHERE metric = ? AND date BETWEEN ? AND ?
                   ORDER BY date ASC""",
                (metric, s, e),
            ).fetchall()
            return [{"date": r["date"], "payload": json.loads(r["payload"])} for r in rows]

    def get_latest(self, metric: str) -> dict | None:
        with _conn() as c:
            row = c.execute(
                """SELECT date, payload FROM garmin_daily_stats
                   WHERE metric = ? ORDER BY date DESC LIMIT 1""",
                (metric,),
            ).fetchone()
            return {"date": row["date"], "payload": json.loads(row["payload"])} if row else None

    def status(self) -> dict[str, Any]:
        with _conn() as c:
            row = c.execute(
                """SELECT MIN(date) AS earliest, MAX(date) AS latest,
                          COUNT(DISTINCT date) AS days,
                          COUNT(*) AS rows
                   FROM garmin_daily_stats"""
            ).fetchone()
            by_metric = c.execute(
                """SELECT metric, COUNT(*) AS n,
                          MIN(date) AS earliest, MAX(date) AS latest
                   FROM garmin_daily_stats GROUP BY metric ORDER BY metric"""
            ).fetchall()
            return {
                "earliest_date": row["earliest"],
                "latest_date": row["latest"],
                "total_days": row["days"] or 0,
                "total_rows": row["rows"] or 0,
                "per_metric": [dict(r) for r in by_metric],
            }

    def get_missing_dates(self, metric: str, start: date_t, end: date_t) -> list[date_t]:
        """Dates in [start, end] that don't have this metric cached."""
        with _conn() as c:
            rows = c.execute(
                "SELECT date FROM garmin_daily_stats WHERE metric = ? AND date BETWEEN ? AND ?",
                (metric, start.isoformat(), end.isoformat()),
            ).fetchall()
        have = {r["date"] for r in rows}
        out = []
        cur = start
        while cur <= end:
            if cur.isoformat() not in have:
                out.append(cur)
            cur += timedelta(days=1)
        return out

    # ---------------------------------------------------------------- sync

    def sync_day(self, d: date_t, force: bool = False) -> int:
        """Sync all per-day metrics for one date. Returns count of rows written.

        force=False skips metrics already cached for this date — useful for
        backfill. force=True refetches (used for "today" which keeps updating).
        """
        if not self.client.enabled:
            return 0
        if not force:
            existing_metrics = self._existing_metrics_for_date(d)
            missing = [m for m in self.client.METRICS_PER_DAY if m not in existing_metrics]
            if not missing:
                return 0
        else:
            missing = list(self.client.METRICS_PER_DAY)

        rows: list[tuple[str, str, Any]] = []
        for metric in missing:
            fn = getattr(self.client, self.client.PER_DAY_DISPATCH[metric])
            payload = fn(d)
            if payload is not None:
                rows.append((d.isoformat(), metric, payload))
            time.sleep(_PER_CALL_DELAY_S)
        self.upsert_many(rows)
        return len(rows)

    def _existing_metrics_for_date(self, d: date_t) -> set[str]:
        with _conn() as c:
            rows = c.execute(
                "SELECT metric FROM garmin_daily_stats WHERE date = ?",
                (d.isoformat(),),
            ).fetchall()
            return {r["metric"] for r in rows}

    def sync_range_metrics(self, start: date_t, end: date_t) -> int:
        """Fetch range-capable metrics (body_battery, daily_steps, body_composition)
        in 90-day chunks. Always overwrites — these calls are cheap and the
        ranges are easier to handle wholesale.
        """
        if not self.client.enabled:
            return 0
        written = 0
        cur = start
        while cur <= end:
            chunk_end = min(cur + timedelta(days=_RANGE_CHUNK_DAYS - 1), end)
            written += self._sync_body_battery(cur, chunk_end)
            written += self._sync_daily_steps(cur, chunk_end)
            written += self._sync_body_composition(cur, chunk_end)
            cur = chunk_end + timedelta(days=1)
        return written

    def _sync_body_battery(self, start: date_t, end: date_t) -> int:
        data = self.client.fetch_body_battery(start, end)
        time.sleep(_PER_CALL_DELAY_S)
        rows = []
        for entry in data or []:
            d = entry.get("date") or entry.get("calendarDate")
            if d:
                rows.append((str(d), "body_battery", entry))
        self.upsert_many(rows)
        return len(rows)

    def _sync_daily_steps(self, start: date_t, end: date_t) -> int:
        data = self.client.fetch_daily_steps(start, end)
        time.sleep(_PER_CALL_DELAY_S)
        rows = []
        for entry in data or []:
            d = entry.get("calendarDate")
            if d:
                rows.append((str(d), "daily_steps", entry))
        self.upsert_many(rows)
        return len(rows)

    def _sync_body_composition(self, start: date_t, end: date_t) -> int:
        data = self.client.fetch_body_composition(start, end)
        time.sleep(_PER_CALL_DELAY_S)
        if not data:
            return 0
        rows = []
        for entry in data.get("dateWeightList", []) or []:
            d = entry.get("calendarDate")
            if d:
                rows.append((str(d), "body_composition", entry))
        self.upsert_many(rows)
        return len(rows)

    # ---------------------------------------------------------------- high-level

    def sync_recent(self, days: int = 14) -> int:
        """Refresh the last `days` days. Today + yesterday always force-refetched
        (data still being recorded); older days only fill gaps."""
        if not self.client.enabled:
            return 0
        today = date_t.today()
        start = today - timedelta(days=days - 1)
        total = 0
        # per-day metrics: gaps + force today/yesterday
        cur = start
        while cur <= today:
            force = cur >= today - timedelta(days=1)
            total += self.sync_day(cur, force=force)
            cur += timedelta(days=1)
        # range metrics: always refresh for the window
        total += self.sync_range_metrics(start, today)
        return total

    def sync_full(self) -> dict[str, Any]:
        """Backfill from today walking backwards until _EMPTY_STREAK_TO_STOP
        consecutive days return no sleep data. Skips days already cached for
        each per-day metric. Range metrics are fetched in 90-day chunks for
        the resulting span.

        Returns a summary dict for the API response.
        """
        if not self.client.enabled:
            return {"started": False, "reason": "garmin client disabled"}

        today = date_t.today()
        # Walk back day by day calling sync_day. The "stop" signal is
        # _EMPTY_STREAK_TO_STOP days in a row with no sleep payload.
        empty_streak = 0
        cur = today
        days_walked = 0
        rows_written = 0
        earliest_with_data: date_t | None = None
        start_t = time.monotonic()

        while empty_streak < _EMPTY_STREAK_TO_STOP:
            rows_written += self.sync_day(cur, force=(cur >= today - timedelta(days=1)))
            days_walked += 1
            # Cheapest way to check if the day produced anything: did sleep land?
            if self.get(cur, "sleep") is not None:
                empty_streak = 0
                earliest_with_data = cur
            else:
                empty_streak += 1
            cur -= timedelta(days=1)
            # safety bound: never walk past 10 years even if Garmin keeps replying
            if days_walked > 3650:
                break

        if earliest_with_data is None:
            return {
                "started": True,
                "days_walked": days_walked,
                "rows_written": rows_written,
                "elapsed_s": round(time.monotonic() - start_t, 1),
                "earliest_with_data": None,
            }

        rows_written += self.sync_range_metrics(earliest_with_data, today)

        return {
            "started": True,
            "days_walked": days_walked,
            "rows_written": rows_written,
            "elapsed_s": round(time.monotonic() - start_t, 1),
            "earliest_with_data": earliest_with_data.isoformat(),
        }
