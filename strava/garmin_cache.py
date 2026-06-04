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
from strava.garmin_extractors import SUMMARY_METRICS, extract

logger = logging.getLogger(__name__)

DB_PATH = Path(".strava/calendar.db")

_PER_CALL_DELAY_S = 0.3            # be polite to Garmin between API calls
_MAX_CONSECUTIVE_ERROR_DAYS = 5   # abort backfill if Garmin keeps failing
_BACKFILL_MAX_RUNTIME_S = 2 * 3600  # wall-clock backstop for a full backfill (resumable — re-run continues)

# Per-endpoint range limits (days per call). daily_steps tolerates a full year
# in one call (great for cheaply mapping data presence); body_battery 400s above
# ~31 days; body_composition (weigh-ins) is sparse and fine in big chunks.
_STEPS_CHUNK_DAYS = 365
_BODY_BATTERY_CHUNK_DAYS = 28
_BODY_COMPOSITION_CHUNK_DAYS = 90

# Backfill floor detection scans body_battery (watch-only — ignores phone-step
# history) backwards until this many consecutive days have no data, so a
# non-wear gap shorter than a year can't truncate the detected history.
_SCAN_EMPTY_DAYS_TO_STOP = 365


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    # WAL lets the API keep reading calendar.db while a long backfill writes;
    # busy_timeout makes any contention wait briefly instead of raising
    # "database is locked". WAL is a persisted file property (set here too so
    # CLI/telegram contexts that skip init_db still get it); busy_timeout is
    # per-connection. Both must run before any transaction opens.
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA journal_mode=WAL")
    return c


class GarminDailyStatsCache:
    """CRUD + sync orchestration over the `garmin_daily_stats` table."""

    def __init__(self, client: GarminClient):
        self.client = client
        # Single sync worker at a time (writes interleave fine but the
        # garminconnect HTTP session isn't safe to hammer concurrently).
        self._sync_lock = threading.Lock()
        # Cooperative cancel for long backfills: request_cancel() sets it, the
        # sync loops check it. Only one sync runs at a time (see _sync_lock).
        self._cancel = threading.Event()
        self._ensure_summary_table()

    def _ensure_summary_table(self) -> None:
        """Create the derived-summary table if the web app's init_db hasn't
        (covers CLI / telegram contexts that use the cache without the API)."""
        with _conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS garmin_daily_summary (
                       date TEXT NOT NULL,
                       metric TEXT NOT NULL,
                       summary TEXT NOT NULL,
                       PRIMARY KEY (date, metric)
                   )"""
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_garmin_summary_metric_date "
                "ON garmin_daily_summary(metric, date)"
            )

    def request_cancel(self) -> None:
        """Ask an in-progress sync (e.g. a long backfill) to stop at the next
        loop check. No-op if nothing is running; the flag is cleared at the
        start of each sync so it never bleeds into the next run."""
        self._cancel.set()

    # ---------------------------------------------------------------- writes

    def upsert(self, d: date_t | str, metric: str, payload: Any) -> None:
        iso = d if isinstance(d, str) else d.isoformat()
        self.upsert_many([(iso, metric, payload)])

    def upsert_many(self, rows: list[tuple[str, str, Any]]) -> None:
        """rows = [(date_iso, metric, payload_dict_or_list), ...].

        Writes the raw payload and, for metrics that feed the trends charts,
        the derived slim summary (see strava/garmin_extractors). Null payloads
        are skipped — leaving a 'missing' gap we can refetch."""
        items: list[tuple[str, str, str]] = []
        summaries: list[tuple[str, str, str]] = []
        for d, m, p in rows:
            if p is None:
                continue
            items.append((d, m, json.dumps(p, default=str)))
            slim = extract(m, p)
            if slim is not None:
                summaries.append((d, m, json.dumps(slim, default=str)))
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
            if summaries:
                c.executemany(
                    """INSERT INTO garmin_daily_summary (date, metric, summary)
                       VALUES (?, ?, ?)
                       ON CONFLICT(date, metric) DO UPDATE SET
                         summary = excluded.summary""",
                    summaries,
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

    def get_summary_range(self, metric: str, start: date_t | str, end: date_t | str) -> list[dict]:
        """Slim chart summaries for a metric over [start, end], date-ascending.
        Reads garmin_daily_summary (a few hundred bytes/day) instead of the fat
        payloads in garmin_daily_stats — this is what powers /trends."""
        s = start if isinstance(start, str) else start.isoformat()
        e = end if isinstance(end, str) else end.isoformat()
        with _conn() as c:
            rows = c.execute(
                """SELECT date, summary FROM garmin_daily_summary
                   WHERE metric = ? AND date BETWEEN ? AND ?
                   ORDER BY date ASC""",
                (metric, s, e),
            ).fetchall()
            return [{"date": r["date"], "summary": json.loads(r["summary"])} for r in rows]

    def backfill_missing_summaries(self) -> int:
        """One-time migration: derive slim summaries for cached payloads that
        don't have one yet. Idempotent — a no-op once every payload has a
        summary, so it's safe to call on every startup. Returns rows written."""
        written = 0
        with _conn() as c:
            for metric in SUMMARY_METRICS:
                rows = c.execute(
                    """SELECT s.date AS date, s.payload AS payload
                       FROM garmin_daily_stats s
                       LEFT JOIN garmin_daily_summary m
                         ON m.date = s.date AND m.metric = s.metric
                       WHERE s.metric = ? AND m.date IS NULL""",
                    (metric,),
                ).fetchall()
                slim = []
                for r in rows:
                    out = extract(metric, json.loads(r["payload"]))
                    if out is not None:
                        slim.append((r["date"], metric, json.dumps(out, default=str)))
                if slim:
                    c.executemany(
                        """INSERT INTO garmin_daily_summary (date, metric, summary)
                           VALUES (?, ?, ?)
                           ON CONFLICT(date, metric) DO UPDATE SET
                             summary = excluded.summary""",
                        slim,
                    )
                    written += len(slim)
        if written:
            logger.info("Garmin: backfilled %d derived daily summaries", written)
        return written

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

    # ---------------------------------------------------------------- sync

    def sync_day(self, d: date_t, refresh_intraday: bool = False) -> int:
        """Sync per-day metrics for one date. Returns count of rows written.

        Missing metrics are always fetched (gap-fill). When refresh_intraday is
        True — used for recent days that are still accumulating — already-cached
        intraday metrics are re-fetched too, but only when the watch has
        uploaded since we last cached this day. Garmin's API is frozen between
        watch uploads, so an idle watch means nothing changed; we detect that
        with a single user_summary read (it carries lastSyncTimestampGMT and is
        a metric we'd refresh anyway). The stable overnight metrics (sleep, hrv)
        are never re-fetched once cached.
        """
        if not self.client.enabled:
            return 0
        existing = self._existing_metrics_for_date(d)
        stable = self.client.STABLE_METRICS
        iso = d.isoformat()
        rows: list[tuple[str, str, Any]] = []

        # Freshness gate: on a recent day, probe with user_summary first and
        # only refresh the other present intraday metrics if the watch actually
        # uploaded since last time. user_summary is handled here, so the loop
        # below skips it.
        refresh_present: list[str] = []
        if refresh_intraday:
            fresh_summary = self.client.fetch_user_summary(d)
            time.sleep(_PER_CALL_DELAY_S)
            if fresh_summary is not None:
                rows.append((iso, "user_summary", fresh_summary))
            if self._watch_uploaded_since_cache(d, fresh_summary, existing):
                refresh_present = [
                    m for m in self.client.METRICS_PER_DAY
                    if m in existing and m not in stable
                ]

        to_fetch = [
            m for m in self.client.METRICS_PER_DAY
            if (m not in existing or m in refresh_present)
            and not (refresh_intraday and m == "user_summary")
        ]
        for metric in to_fetch:
            fn = getattr(self.client, self.client.PER_DAY_DISPATCH[metric])
            payload = fn(d)
            if payload is not None:
                rows.append((iso, metric, payload))
            time.sleep(_PER_CALL_DELAY_S)

        if not rows:
            return 0
        self.upsert_many(rows)
        return len(rows)

    def _watch_uploaded_since_cache(
        self, d: date_t, fresh_summary: Any, existing: set[str]
    ) -> bool:
        """Has the watch uploaded since we last cached this day? Compares
        user_summary.lastSyncTimestampGMT against the cached value. Returns True
        (refresh) whenever we can't be sure — no fresh read, no cached summary,
        or the field is absent — so the gate only ever saves work, never skips
        data that actually changed."""
        if fresh_summary is None or "user_summary" not in existing:
            return True
        new_ts = fresh_summary.get("lastSyncTimestampGMT")
        if not new_ts:
            return True
        cached = self.get(d, "user_summary") or {}
        return new_ts != cached.get("lastSyncTimestampGMT")

    def _existing_metrics_for_date(self, d: date_t) -> set[str]:
        with _conn() as c:
            rows = c.execute(
                "SELECT metric FROM garmin_daily_stats WHERE date = ?",
                (d.isoformat(),),
            ).fetchall()
            return {r["metric"] for r in rows}

    def sync_range_metrics(self, start: date_t, end: date_t) -> int:
        """Fetch range-capable metrics (body_battery, daily_steps, body_composition).
        Each has its own per-call range limit — body_battery 400s above ~31 days,
        so they can't share one chunk size (the old 90-day chunk silently broke
        body_battery backfill). Always overwrites; cheap relative to per-day calls.
        """
        if not self.client.enabled:
            return 0
        return (
            self._sync_chunked(start, end, self._sync_body_battery, _BODY_BATTERY_CHUNK_DAYS)
            + self._sync_chunked(start, end, self._sync_daily_steps, _STEPS_CHUNK_DAYS)
            + self._sync_chunked(start, end, self._sync_body_composition, _BODY_COMPOSITION_CHUNK_DAYS)
        )

    def _sync_chunked(self, start: date_t, end: date_t, fn, chunk_days: int) -> int:
        written = 0
        cur = start
        while cur <= end:
            if self._cancel.is_set():
                break
            chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
            written += fn(cur, chunk_end)
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
        """Refresh the last `days` days. Today + yesterday re-fetch their
        intraday metrics (data still being recorded); older days only fill
        gaps. Stable overnight metrics (sleep, hrv) are never re-fetched once
        cached — see sync_day."""
        if not self.client.enabled:
            return 0
        self._cancel.clear()
        today = date_t.today()
        start = today - timedelta(days=days - 1)
        total = 0
        # per-day metrics: gaps everywhere + intraday refresh for today/yesterday
        cur = start
        while cur <= today:
            if self._cancel.is_set():
                return total
            refresh = cur >= today - timedelta(days=1)
            total += self.sync_day(cur, refresh_intraday=refresh)
            cur += timedelta(days=1)
        # range metrics: always refresh for the window
        total += self.sync_range_metrics(start, today)
        return total

    def sync_full(self) -> dict[str, Any]:
        """Backfill all available history.

        Detection: a body_battery scan (_scan_active_days) maps which days the
        watch recorded wellness data and finds the true floor. body_battery is
        watch-only, so it ignores phone-step history, and it keeps scanning past
        gaps shorter than a year — a consecutive-empty-day walk would instead
        stop at the first long non-wear gap and silently drop everything older.

        Then per-day metrics are fetched only for active days that aren't already
        fully cached, plus range metrics for the whole span. Stops early on
        request_cancel(), a `_BACKFILL_MAX_RUNTIME_S` wall-clock cap, or repeated
        API errors — all resumable, since cached days are skipped on a re-run.

        Returns a summary dict for the API response.
        """
        if not self.client.enabled:
            return {"started": False, "reason": "garmin client disabled"}

        self._cancel.clear()
        today = date_t.today()
        start_t = time.monotonic()
        deadline = start_t + _BACKFILL_MAX_RUNTIME_S

        active_days, floor, scan_status = self._scan_active_days(today)
        if scan_status != "ok":
            # "error" -> scan_error; "cancelled" -> cancelled
            return {"started": True,
                    "stop_reason": "scan_error" if scan_status == "error" else scan_status,
                    "elapsed_s": round(time.monotonic() - start_t, 1)}
        if floor is None:
            return {"started": True, "stop_reason": "no_data",
                    "active_days": 0, "days_fetched": 0, "rows_written": 0,
                    "elapsed_s": round(time.monotonic() - start_t, 1)}

        # Skip days already fully cached; fetch the rest, newest first.
        complete = self._complete_dates(floor, today)
        candidates = sorted((d for d in active_days if d not in complete), reverse=True)

        rows_written = 0
        days_fetched = 0
        consecutive_errors = 0
        stop_reason = "complete"
        for iso in candidates:
            if self._cancel.is_set():
                stop_reason = "cancelled"
                break
            if time.monotonic() > deadline:
                stop_reason = "max_runtime"
                break
            d = date_t.fromisoformat(iso)
            errors_before = self.client.call_errors
            rows_written += self.sync_day(d, refresh_intraday=(d >= today - timedelta(days=1)))
            days_fetched += 1
            # Bail if Garmin keeps failing rather than grinding the whole span.
            if self.client.call_errors > errors_before:
                consecutive_errors += 1
                if consecutive_errors >= _MAX_CONSECUTIVE_ERROR_DAYS:
                    stop_reason = "too_many_errors"
                    break
            else:
                consecutive_errors = 0

        # Only sync range metrics on a clean finish — a cancelled/timed-out run
        # is resumable, so don't prolong it with the trailing range fetches.
        if stop_reason == "complete":
            rows_written += self.sync_range_metrics(floor, today)

        return {
            "started": True,
            "stop_reason": stop_reason,
            "data_floor": floor.isoformat(),
            "active_days": len(active_days),
            "days_fetched": days_fetched,
            "days_skipped_cached": len(active_days) - len(candidates),
            "rows_written": rows_written,
            "elapsed_s": round(time.monotonic() - start_t, 1),
        }

    def _scan_active_days(
        self, today: date_t, max_days_back: int = 3650
    ) -> tuple[set[str], date_t | None, str]:
        """Map which days the watch recorded wellness data by scanning
        body_battery in chunks backwards. body_battery is watch-only, so it
        ignores phone-step history and pins the floor to the real wellness era.
        Keeps scanning until a full year has no data (`_SCAN_EMPTY_DAYS_TO_STOP`),
        so a non-wear gap shorter than that can't truncate the floor.

        Returns (active date-isos, earliest such date, status) where status is
        "ok", "error" (a fetch failed — abort rather than guess a floor, which
        would silently lose history), or "cancelled"."""
        active: set[str] = set()
        floor_iso: str | None = None
        empty_run_days = 0
        cur_end = today
        while (today - cur_end).days < max_days_back:
            if self._cancel.is_set():
                return active, (date_t.fromisoformat(floor_iso) if floor_iso else None), "cancelled"
            chunk_start = cur_end - timedelta(days=_BODY_BATTERY_CHUNK_DAYS - 1)
            errors_before = self.client.call_errors
            data = self.client.fetch_body_battery(chunk_start, cur_end)
            time.sleep(_PER_CALL_DELAY_S)
            if self.client.call_errors > errors_before:
                return active, (date_t.fromisoformat(floor_iso) if floor_iso else None), "error"
            # The range endpoint returns an entry for *every* calendar day, even
            # before the watch existed (bodyBatteryValuesArray is always a small
            # descriptor array). charged/drained are None on no-data days and
            # real numbers once the watch recorded body battery — that's the
            # reliable "watch was worn" signal.
            chunk_days = {
                (e.get("date") or e.get("calendarDate")) for e in (data or [])
                if e.get("charged") is not None or e.get("drained") is not None
            }
            chunk_days.discard(None)
            if chunk_days:
                active |= chunk_days
                chunk_floor = min(chunk_days)
                floor_iso = chunk_floor if floor_iso is None else min(floor_iso, chunk_floor)
                empty_run_days = 0
            else:
                empty_run_days += _BODY_BATTERY_CHUNK_DAYS
                if empty_run_days >= _SCAN_EMPTY_DAYS_TO_STOP:
                    break
            cur_end = chunk_start - timedelta(days=1)
        floor = date_t.fromisoformat(floor_iso) if floor_iso else None
        return active, floor, "ok"

    def _complete_dates(self, start: date_t, end: date_t) -> set[str]:
        """Dates in [start, end] that already have *all* per-day metrics cached,
        so backfill can skip them wholesale. Partially-cached days fall through
        to sync_day, which gap-fills only what's missing."""
        metrics = self.client.METRICS_PER_DAY
        placeholders = ",".join("?" * len(metrics))
        with _conn() as c:
            rows = c.execute(
                f"""SELECT date FROM garmin_daily_stats
                    WHERE metric IN ({placeholders}) AND date BETWEEN ? AND ?
                    GROUP BY date HAVING COUNT(DISTINCT metric) >= ?""",
                (*metrics, start.isoformat(), end.isoformat(), len(metrics)),
            ).fetchall()
        return {r["date"] for r in rows}
