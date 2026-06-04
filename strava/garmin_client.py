"""Thin wrapper around `garminconnect` for daily watch-level wellness stats.

Strava remains the source of truth for activities; this client only exposes
the metrics Garmin records that Strava doesn't surface (sleep, HRV, training
readiness, body battery, etc.).

Design notes
------------
- Graceful disable: if GARMIN_EMAIL / GARMIN_PASSWORD are missing or login
  fails, `enabled` stays False and every fetch returns None. The rest of the
  app never sees an exception.
- Token cache: `garminconnect` persists OAuth tokens to GARMINTOKENS. The
  web app sets that env var to `<workdir>/garmin` before instantiating this
  class (see backend/app.py lifespan).
- MFA: handled interactively on first login only. From a web server context
  there is no stdin, so the prompt_mfa callback raises a clean error
  pointing the user at `scripts/garmin_login.py`.
- All garminconnect methods are synchronous; callers running on the event
  loop must wrap calls in `asyncio.to_thread(...)`.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date as date_t
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Transient errors worth retrying with backoff (rate limits, connection blips)
# rather than treating as "no data". Imported defensively so a missing lib
# leaves the client disabled instead of failing at import.
try:
    from garminconnect import (
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
    )
    _RETRYABLE: tuple[type[Exception], ...] = (
        GarminConnectTooManyRequestsError,
        GarminConnectConnectionError,
    )
except Exception:  # pragma: no cover - lib absent → client never enables anyway
    _RETRYABLE = ()

_MAX_RETRIES = 3        # attempts per call before giving up
_BACKOFF_BASE_S = 2.0   # exponential: 2s, 4s, ... between retries


class GarminMFARequired(RuntimeError):
    """Raised when Garmin asks for an MFA code but no interactive stdin is
    available. Tells the caller to provision the token via the CLI helper."""


def _mfa_not_interactive() -> str:
    raise GarminMFARequired(
        "Garmin Connect requires MFA but the web server has no stdin. "
        "Run `poetry run python scripts/garmin_login.py` once from a "
        "terminal to refresh the cached token, then restart the backend."
    )


class GarminClient:
    """Lazy, optional Garmin Connect client.

    Construction never raises. Call `ensure_logged_in()` (sync, blocking) to
    actually log in — typically once at startup. After that `enabled` is
    True and fetch_* methods return raw JSON payloads from the lib.
    """

    METRICS_PER_DAY: tuple[str, ...] = (
        "user_summary",
        "sleep",
        "hrv",
        "training_readiness",
        "training_status",
        "stress",
        "heart_rates",
        "spo2",
        "respiration",
        "intensity_minutes",
    )
    METRICS_RANGE: tuple[str, ...] = (
        "body_battery",
        "daily_steps",
        "body_composition",
    )
    ALL_METRICS: tuple[str, ...] = METRICS_PER_DAY + METRICS_RANGE

    # Per-day metrics derived from a completed overnight sleep session: once
    # they land in the morning they don't change for the rest of the day, so
    # the sync fetches them once and never force-refreshes them. Everything
    # else in METRICS_PER_DAY accumulates through the day (steps, stress, HR,
    # intensity minutes, readiness) and is refreshed for recent days.
    #
    # Grounded in scripts/garmin_intraday_probe.py: Garmin's API only advances
    # when the watch uploads (data froze at the last `lastSyncTimestampGMT`),
    # and sleep/hrv are computed from the finished night — re-pulling sleep's
    # ~260KB payload on every 6h auto-sync was pure waste.
    STABLE_METRICS: frozenset[str] = frozenset({"sleep", "hrv"})

    def __init__(self, email: str | None, password: str | None, token_dir: Path):
        self.email = email
        self.password = password
        self.token_dir = token_dir
        self.token_dir.mkdir(parents=True, exist_ok=True)
        self.enabled: bool = False
        self.last_error: str | None = None
        # Count of fetches that failed for real (retries exhausted / non-transient),
        # so sync loops can tell a failed day apart from a genuinely empty one.
        self.call_errors: int = 0
        self._client = None  # garminconnect.Garmin lazy-loaded
        self._lock = threading.Lock()

        if not email or not password:
            self.last_error = "GARMIN_EMAIL / GARMIN_PASSWORD not set in .env"
            logger.info("Garmin client disabled: %s", self.last_error)

    # ------------------------------------------------------------------ login

    def ensure_logged_in(self) -> bool:
        """Log in to Garmin (idempotent). Returns True on success."""
        if self.enabled and self._client is not None:
            return True
        if not self.email or not self.password:
            return False
        with self._lock:
            if self.enabled and self._client is not None:
                return True
            try:
                from garminconnect import Garmin
                client = Garmin(
                    self.email,
                    self.password,
                    prompt_mfa=_mfa_not_interactive,
                )
                client.login(str(self.token_dir))
                self._client = client
                self.enabled = True
                self.last_error = None
                logger.info("Garmin client logged in (token cache: %s)", self.token_dir)
                return True
            except GarminMFARequired as e:
                self.last_error = str(e)
                logger.warning("Garmin login needs MFA: %s", e)
                return False
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                logger.warning("Garmin login failed: %s", self.last_error)
                return False

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _iso(d: date_t | str) -> str:
        return d if isinstance(d, str) else d.isoformat()

    def _call(self, fn_name: str, *args) -> Any:
        """Invoke a `Garmin.<fn_name>` method, return None on failure.

        Rate-limit / transient connection errors are retried with exponential
        backoff, so a `None` return means 'no data' or a non-transient failure —
        not a blip. When retries are exhausted (or the error isn't retryable)
        `call_errors` is bumped, letting sync loops distinguish a failed day
        from an empty one. Never raises: one bad day shouldn't abort a batch.
        """
        if not self.ensure_logged_in():
            return None
        for attempt in range(_MAX_RETRIES):
            try:
                return getattr(self._client, fn_name)(*args)
            except _RETRYABLE as e:
                if attempt == _MAX_RETRIES - 1:
                    break
                wait = _BACKOFF_BASE_S * (2 ** attempt)
                logger.warning(
                    "Garmin %s rate-limited/transient (attempt %d/%d), backing off %.0fs: %s",
                    fn_name, attempt + 1, _MAX_RETRIES, wait, e,
                )
                time.sleep(wait)
            except Exception as e:
                logger.warning("Garmin %s%s failed: %s: %s", fn_name, args, type(e).__name__, e)
                self.call_errors += 1
                return None
        self.call_errors += 1
        logger.warning("Garmin %s failed after %d retries (giving up)", fn_name, _MAX_RETRIES)
        return None

    # ------------------------------------------------------------------ per-day fetches

    def fetch_user_summary(self, d): return self._call("get_user_summary", self._iso(d))
    def fetch_sleep(self, d):        return self._call("get_sleep_data", self._iso(d))
    def fetch_hrv(self, d):          return self._call("get_hrv_data", self._iso(d))
    def fetch_training_status(self, d): return self._call("get_training_status", self._iso(d))
    def fetch_stress(self, d):       return self._call("get_stress_data", self._iso(d))
    def fetch_heart_rates(self, d):  return self._call("get_heart_rates", self._iso(d))
    def fetch_spo2(self, d):         return self._call("get_spo2_data", self._iso(d))
    def fetch_respiration(self, d):  return self._call("get_respiration_data", self._iso(d))
    def fetch_intensity_minutes(self, d): return self._call("get_intensity_minutes_data", self._iso(d))

    def fetch_training_readiness(self, d):
        """Garmin returns a list of intraday snapshots; we keep the latest by
        timestamp (which represents the most up-to-date assessment for the day).
        Stored as a single dict in the cache for simplicity."""
        raw = self._call("get_training_readiness", self._iso(d))
        if not raw:
            return None
        if isinstance(raw, list):
            if not raw:
                return None
            # latest snapshot wins — sort by timestamp string (ISO-ordered)
            raw = sorted(raw, key=lambda x: x.get("timestamp", ""))[-1]
        return raw

    # ------------------------------------------------------------------ range fetches

    def fetch_body_battery(self, start, end):
        """Returns list[dict] — one entry per day in [start, end]."""
        return self._call("get_body_battery", self._iso(start), self._iso(end)) or []

    def fetch_daily_steps(self, start, end):
        return self._call("get_daily_steps", self._iso(start), self._iso(end)) or []

    def fetch_body_composition(self, start, end):
        """Returns dict with `dateWeightList`. Empty for users without an Index scale."""
        return self._call("get_body_composition", self._iso(start), self._iso(end))

    # ------------------------------------------------------------------ orchestration

    PER_DAY_DISPATCH: dict[str, str] = {
        "user_summary":       "fetch_user_summary",
        "sleep":              "fetch_sleep",
        "hrv":                "fetch_hrv",
        "training_readiness": "fetch_training_readiness",
        "training_status":    "fetch_training_status",
        "stress":             "fetch_stress",
        "heart_rates":        "fetch_heart_rates",
        "spo2":               "fetch_spo2",
        "respiration":        "fetch_respiration",
        "intensity_minutes":  "fetch_intensity_minutes",
    }
