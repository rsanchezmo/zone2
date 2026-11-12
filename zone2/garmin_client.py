"""Thin wrapper around `garminconnect` for daily watch-level wellness stats.

Strava remains the source of truth for activities; this client only exposes
the metrics Garmin records that Strava doesn't surface (sleep, HRV, training
readiness, body battery, etc.).

Design notes
------------
- Graceful disable: without a sign-in (tokens) or GARMIN_EMAIL / GARMIN_PASSWORD,
  or when login fails, `enabled` stays False and every fetch returns None. The
  rest of the app never sees an exception.
- Sign-in: `begin_sign_in` / `finish_sign_in` take the email and password once,
  and the code Garmin sends when it asks for one; only the tokens are kept.
- Token cache: `garminconnect` persists its tokens in `token_dir`, which
  Zone2 sets to GARMINTOKENS when given, else `garmin/` in its data directory.
- MFA: a background login from .env credentials can't ask for the code, so the
  prompt_mfa callback raises a clean error pointing at the Profile page.
- All garminconnect methods are synchronous; callers running on the event
  loop must wrap calls in `asyncio.to_thread(...)`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
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
    """Raised when Garmin asks a background login for the code it sent."""


def _mfa_not_interactive() -> str:
    raise GarminMFARequired("Garmin asks for a code to sign in: connect Garmin from z2's Profile page.")


class GarminSignInRefused(RuntimeError):
    """Garmin turned down the email and password, or the code."""


class GarminSignInFailed(RuntimeError):
    """Garmin couldn't be reached or is limiting sign-ins, so try again later."""


# The file garminconnect keeps its tokens in, inside the token dir
TOKENS_FILE = "garmin_tokens.json"
# How long a sign-in waits for the code Garmin sent
SIGN_IN_TTL_S = 600


@contextmanager
def _sign_in_errors(what: str) -> Iterator[None]:
    """The lib's sign-in errors as GarminSignInRefused or GarminSignInFailed, fit to show."""
    from garminconnect import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
    try:
        yield
    except GarminConnectAuthenticationError as e:
        logger.info("Garmin refused %s: %s", what, e)
        raise GarminSignInRefused(f"Garmin didn't accept {what}.") from e
    except GarminConnectTooManyRequestsError as e:
        raise GarminSignInFailed("Garmin is limiting sign-ins from this network: try again in a while.") from e
    except Exception as e:
        logger.warning("Garmin sign-in failed: %s: %s", type(e).__name__, e)
        raise GarminSignInFailed("Garmin can't be reached right now: try again in a minute.") from e


class GarminUnavailable(RuntimeError):
    """Garmin Connect isn't logged in (the reason is GarminClient.last_error)."""


class GarminNotFound(RuntimeError):
    """What a user action points at no longer exists in Garmin Connect."""


def _is_missing(e: Exception) -> bool:
    # The lib reports every HTTP error as GarminConnectConnectionError("API Error <status> - ...")
    return "API Error 404" in str(e)


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
        "all_day_events",
    )
    METRICS_RANGE: tuple[str, ...] = (
        "body_battery",
        "daily_steps",
        "body_composition",
        "race_predictions",
        "max_metrics",
    )
    ALL_METRICS: tuple[str, ...] = METRICS_PER_DAY + METRICS_RANGE

    # Per-day metrics derived from a completed overnight sleep session: once
    # they land *scored* in the morning they don't change for the rest of the
    # day, so the sync fetches them once and never force-refreshes them. (An
    # early sync can land before Garmin scores the night, writing an empty
    # placeholder; sync_day re-pulls that until it finalizes — see is_finalized.)
    # Everything
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
        # A sign-in waiting for its code: the lib keeps that state on the client itself
        self._pending: tuple[Any, float] | None = None

        if not self.configured:
            self.last_error = "Garmin isn't connected"
            logger.info("Garmin client disabled: %s", self.last_error)

    @property
    def tokens_file(self) -> Path:
        return self.token_dir / TOKENS_FILE

    @property
    def from_env(self) -> bool:
        """Whether GARMIN_EMAIL and GARMIN_PASSWORD are set, so a sign-out doesn't stick."""
        return bool(self.email and self.password)

    @property
    def configured(self) -> bool:
        """Signed in from the app (its tokens are kept), or credentials in .env."""
        return self.from_env or self.tokens_file.exists()

    # ------------------------------------------------------------------ login

    def ensure_logged_in(self) -> bool:
        """Log in to Garmin (idempotent). Returns True on success."""
        if self.enabled and self._client is not None:
            return True
        if not self.configured:
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
                self.last_error = (f"{type(e).__name__}: {e}" if self.from_env
                                   else "Garmin signed z2 out: connect Garmin again from the Profile page.")
                logger.warning("Garmin login failed: %s: %s", type(e).__name__, e)
                return False

    def begin_sign_in(self, email: str, password: str) -> bool:
        """Sign in with the athlete's email and password, which are never stored: the tokens
        are. Returns True when Garmin asks for the code it sent, for `finish_sign_in`."""
        from garminconnect import Garmin
        client = Garmin(email, password, return_on_mfa=True)
        with _sign_in_errors("that email and password"):
            status, _ = client.login()
        if status == "needs_mfa":
            with self._lock:
                self._pending = (client, time.monotonic())
            return True
        self._adopt(client)
        return False

    def finish_sign_in(self, code: str) -> None:
        """Finish the sign-in `begin_sign_in` started with the code Garmin sent. A refused code
        keeps it waiting, for another try."""
        with self._lock:
            pending = self._pending
        if pending is None or time.monotonic() - pending[1] > SIGN_IN_TTL_S:
            raise GarminSignInRefused("That sign-in expired: enter your email and password again.")
        client = pending[0]
        with _sign_in_errors("that code"):
            client.resume_login(None, code)
        with self._lock:
            self._pending = None
        self._adopt(client)

    def _adopt(self, client: Any) -> None:
        """Keep a finished sign-in's tokens and log in from them, which loads the profile."""
        client.client.dump(str(self.tokens_file))
        with self._lock:
            self._client, self.enabled, self.last_error = None, False, None
        if not self.ensure_logged_in():
            raise GarminSignInFailed(self.last_error or "Garmin signed in but its session doesn't load")

    def sign_out(self) -> None:
        """Forget the sign-in made in the app: its tokens and the logged-in client."""
        with self._lock:
            self.tokens_file.unlink(missing_ok=True)
            self._client, self.enabled, self._pending = None, False, None
            self.last_error = "Garmin isn't connected"

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

    def fetch_all_day_events(self, d):
        """Move IQ auto-detected activities (walking, biking, …) for a day —
        list[dict], present even when nothing was recorded on the watch."""
        return self._call("get_all_day_events", self._iso(d))

    def fetch_training_readiness(self, d):
        """Garmin returns a list of intraday snapshots; we keep the latest by
        timestamp (the most up-to-date assessment), as a single dict, with the
        wake-up snapshot under `wakeup`: the one to plan the day's training on,
        before the day's activity drains the later ones."""
        raw = self._call("get_training_readiness", self._iso(d))
        if not raw:
            return None
        if isinstance(raw, list):
            snapshots = sorted(raw, key=lambda x: x.get("timestamp", ""))
            raw = dict(snapshots[-1])
            wakeup = next((s for s in snapshots if s.get("inputContext") == "AFTER_WAKEUP_RESET"), None)
            if wakeup is not None:
                raw["wakeup"] = wakeup
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

    def fetch_race_predictions(self, start, end):
        """Returns list[dict] — Garmin's race predictor (time5K/time10K/
        timeHalfMarathon/timeMarathon, seconds), one entry per day."""
        return self._call("get_race_predictions", self._iso(start), self._iso(end), "daily") or []

    def fetch_max_metrics(self, start, end):
        """Returns list[dict] — VO2 max (`generic` for running, `cycling`) and
        fitness age, one entry per day Garmin updated them. The lib only asks
        for a single day; the endpoint takes a span."""
        return self._call(
            "connectapi", f"/metrics-service/metrics/maxmet/daily/{self._iso(start)}/{self._iso(end)}",
        ) or []

    # ------------------------------------------------------------------ courses
    # The Connect web app's course endpoints (the lib has none). User actions,
    # so unlike the fetches above they raise instead of returning None.

    def _logged_in(self) -> Any:
        """The lib's client, logged in, for user actions (which raise rather than return None)."""
        if not self.ensure_logged_in():
            raise GarminUnavailable(self.last_error or "Garmin Connect is not connected")
        return self._client

    def _request(self, method: str, path: str, **kwargs) -> Any:
        return self._logged_in().client.request(method, "connect", path, **kwargs)

    def list_courses(self) -> list[dict]:
        return self._request("GET", "/course-service/course").json()

    def course_points(self, course_id: int) -> list[tuple[float, float]]:
        """(lat, lon) of each point of a course."""
        course = self._request("GET", f"/course-service/course/{course_id}").json()
        return [(pt["latitude"], pt["longitude"]) for pt in course.get("geoPoints") or []]

    def create_course(self, name: str, gpx: bytes) -> dict:
        """Save a GPX track as a private running course and return it.
        Import only parses the file (per-point distances included); saving
        takes the totals and bounds the web app fills in, and Garmin adds the
        elevation itself."""
        course = self._request("POST", "/course-service/course/import",
                               files={"file": ("course.gpx", gpx, "application/gpx+xml")}).json()
        points = course["geoPoints"]
        if len(points) < 2:
            raise ValueError("The course has fewer than 2 points")
        total = points[-1]["distance"]
        lats, lons = [pt["latitude"] for pt in points], [pt["longitude"] for pt in points]
        course.update({
            "courseName": name,
            "activityTypePk": 1,    # running
            "rulePK": 2,            # private
            "sourceTypeId": 3,
            "distanceMeter": total,
            "startPoint": points[0],
            "coordinateSystem": "WGS84", "targetCoordinateSystem": "WGS84", "originalCoordinateSystem": "WGS84",
            "boundingBox": {"center": None,
                            "lowerLeft": {"latitude": min(lats), "longitude": min(lons)},
                            "upperRight": {"latitude": max(lats), "longitude": max(lons)},
                            "lowerLeftLatIsSet": True, "lowerLeftLongIsSet": True,
                            "upperRightLatIsSet": True, "upperRightLongIsSet": True},
        })
        for line in course.get("courseLines") or []:
            line["distanceInMeters"] = total
        return self._request("POST", "/course-service/course", json=course).json()

    def course_devices(self) -> list[dict]:
        """Watches that take courses, as {device_id, name, primary}; primary
        is the primary training device."""
        devices = self._logged_in().get_primary_training_device()
        primary = (devices.get("PrimaryTrainingDevice") or {}).get("deviceId")
        return [{"device_id": d["deviceId"], "name": d.get("productDisplayName") or d.get("displayName"),
                 "primary": d["deviceId"] == primary}
                for d in devices.get("RegisteredDevices") or [] if d.get("courseCapable")]

    def send_course(self, course_id: int, device_id: int) -> None:
        """Queue a saved course for the watch, which downloads it on its next sync."""
        course = self._request("GET", f"/course-service/course/{course_id}").json()
        self._request("POST", "/device-service/devicemessage/messages", json=[{
            "deviceId": device_id,
            "messageUrl": f"course-service/course/fit/{course_id}/{course['userProfilePk']}?elevation=true",
            "messageType": "courses",
            "messageName": course["courseName"],
            "groupName": None,
            "priority": 1,
            "fileType": "FIT",
            "metaDataId": course_id,
        }])

    # ------------------------------------------------------------------ workouts
    # Saved workouts in the Garmin library and planned sessions on its calendar,
    # which the watch offers on the day (see backend/services/garmin_workouts.py).
    # Raw workout JSON, since the lib's typed models drop step targets.

    def upload_workout(self, workout: dict) -> int:
        """Save a workout to the library and return its id."""
        return int(self._logged_in().upload_workout(workout)["workoutId"])

    def schedule_workout(self, workout_id: int, day: str) -> int:
        """Put a workout on the calendar and return the entry's id. A workout
        can be on many days; GarminNotFound when it was deleted."""
        try:
            return int(self._logged_in().schedule_workout(workout_id, day)["workoutScheduleId"])
        except Exception as e:
            if _is_missing(e):
                raise GarminNotFound(f"Garmin workout {workout_id} no longer exists") from e
            raise

    def unschedule_workout(self, schedule_id: int) -> None:
        """Take one entry off the calendar; one already gone counts as done."""
        try:
            self._logged_in().unschedule_workout(schedule_id)
        except Exception as e:
            if not _is_missing(e):
                raise

    def delete_workout(self, workout_id: int) -> None:
        """Delete a workout from the library, which also removes every calendar
        entry of it. One already deleted counts as done."""
        try:
            self._logged_in().delete_workout(workout_id)
        except Exception as e:
            if not _is_missing(e):
                raise

    def get_workout(self, workout_id: int) -> dict:
        """A library workout with its steps."""
        try:
            return self._logged_in().get_workout_by_id(workout_id)
        except Exception as e:
            if _is_missing(e):
                raise GarminNotFound(f"Garmin workout {workout_id} no longer exists") from e
            raise

    def update_workout(self, workout_id: int, workout: dict) -> None:
        """Replace a library workout's name, notes and steps in place; its
        calendar entries stay and show the new version."""
        current = self.get_workout(workout_id)
        self._request("PUT", f"/workout-service/workout/{workout_id}", json={**current, **workout})

    def list_workouts(self) -> list[dict]:
        return self._logged_in().get_workouts(0, 500)

    def hr_zones(self) -> list[dict]:
        """The HR zones Garmin Connect and the watch use, one entry per sport
        (DEFAULT, RUNNING…), with the method and threshold they're built on.
        The Connect web app's endpoint; the lib has none."""
        return self._request("GET", "/biometric-service/heartRateZones").json()

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
        "all_day_events":     "fetch_all_day_events",
    }
