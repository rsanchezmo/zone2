"""Pure pieces of backend/services: HR zones from Garmin, race matching,
streaks, totals, today's briefing, and the stats response cache."""
from datetime import date, datetime, time, timezone
from types import SimpleNamespace

import pandas as pd

from backend import _ttl_cache
from backend._ttl_cache import TTLCache
from backend.services import training
from backend.services.briefing import Day, Recovery, classify, day_of, is_hard
from backend.services.races import race_activity_ids
from backend.services.zones import zones_from_garmin
from zone2.clock import Clock
from zone2.utils import SportCategory
from tests.synthetic import activities_frame

# ── HR zones from Garmin ─────────────────────────────────────────────────

GARMIN_RUNNING = {"sport": "RUNNING", "zone2Floor": 120, "zone3Floor": 140, "zone4Floor": 155, "zone5Floor": 170,
                  "maxHeartRateUsed": 190, "trainingMethod": "LACTATE_THRESHOLD",
                  "lactateThresholdHeartRateUsed": 165}


def test_garmin_running_zones():
    default = {**GARMIN_RUNNING, "sport": "DEFAULT", "zone2Floor": 100}
    zones, threshold = zones_from_garmin([default, GARMIN_RUNNING])
    assert [(z["min"], z["max"]) for z in zones] == [(0, 120), (120, 140), (140, 155), (155, 170), (170, 190)]
    assert threshold == 165


def test_garmin_default_zones_without_a_threshold():
    zones, threshold = zones_from_garmin([{**GARMIN_RUNNING, "sport": "DEFAULT", "trainingMethod": "HR_MAX"}])
    assert zones[0] == {"min": 0, "max": 120} and threshold is None


def test_unusable_garmin_zones():
    assert zones_from_garmin([{**GARMIN_RUNNING, "zone3Floor": 115}]) is None   # not increasing
    assert zones_from_garmin([{**GARMIN_RUNNING, "zone5Floor": None}]) is None
    assert zones_from_garmin([{"sport": "CYCLING"}]) is None
    assert zones_from_garmin({}) is None


# ── Races from the race calendar ─────────────────────────────────────────

def test_race_events_find_their_activity():
    activities = activities_frame([
        {"id": 10, "sport_type": "Run", "start_date_local": "2026-10-04T09:00:00Z", "distance": 10300.0},
        {"id": 11, "sport_type": "Run", "start_date_local": "2026-10-04T08:20:00Z", "distance": 2000.0},
        {"id": 12, "sport_type": "Ride", "start_date_local": "2026-10-04T15:00:00Z", "distance": 40000.0},
        {"id": 13, "sport_type": "TrailRun", "start_date_local": "2026-10-18T08:00:00Z", "distance": 21500.0},
    ])
    events = [("2026-10-04", "Run", 10.0),     # the race, not its warm-up
              ("2026-10-18", "Run", 21.1),     # a trail run counts for a run event
              ("2026-10-04", "Ride", None),    # no distance: the longest that day
              ("2026-10-25", "Run", 42.2)]     # nothing that day
    assert race_activity_ids(activities, events) == frozenset({10, 12, 13})
    # 5 km: both runs that day are over 25% off
    assert race_activity_ids(activities, [("2026-10-04", "Run", 5.0)]) == frozenset()
    assert race_activity_ids(pd.DataFrame(), events) == frozenset()


# ── Streaks and totals ───────────────────────────────────────────────────

def z2_with(rows: list[dict], today: date = date(2026, 12, 31)) -> SimpleNamespace:
    activities = activities_frame(rows)
    cache = SimpleNamespace(get_prepared_view=lambda: activities, activities_raw=activities)
    noon = datetime.combine(today, time(12), timezone.utc)
    return SimpleNamespace(strava_activities_cache=cache, clock=Clock(lambda: timezone.utc, lambda: noon))


STREAK_DAYS = ["2026-12-24", "2026-12-25", "2026-12-26", "2026-12-29", "2027-01-04", "2027-01-05"]


def test_day_and_week_streaks_across_a_new_year():
    z2 = z2_with([{"sport_type": "Run", "start_date_local": f"{d}T07:00:00Z"} for d in STREAK_DAYS], date(2027, 1, 6))
    streaks = training.streaks(z2)
    assert (streaks["longest_streak"], streaks["longest_streak_start"], streaks["longest_streak_end"]) == (
        3, "2026-12-24", "2026-12-26")
    assert streaks["current_streak"] == 2   # yesterday and the day before
    # ISO weeks 2026-W52, 2026-W53 and 2027-W01 run back to back
    assert (streaks["longest_week_streak"], streaks["longest_week_streak_start"]) == (3, "2026-12-21")
    assert streaks["current_week_streak"] == 3


def test_a_day_off_ends_the_day_streak_but_not_the_week_streak():
    z2 = z2_with([{"sport_type": "Run", "start_date_local": f"{d}T07:00:00Z"} for d in STREAK_DAYS], date(2027, 1, 8))
    streaks = training.streaks(z2)
    assert (streaks["current_streak"], streaks["current_week_streak"]) == (0, 3)


def test_sport_totals_leave_walks_out_of_running():
    z2 = z2_with([
        {"sport_type": sport, "start_date_local": "2026-10-01T08:00:00Z", "distance": km * 1000.0,
         "moving_time": 3600}
        for sport, km in [("Run", 10), ("TrailRun", 12), ("Walk", 5), ("Hike", 8), ("Ride", 30), ("Yoga", 0)]
    ])
    assert training.sport_totals(z2) == {
        SportCategory.RUNNING: {"distance_km": 22.0, "time_s": 7200, "count": 2},
        SportCategory.CYCLING: {"distance_km": 30.0, "time_s": 3600, "count": 1},
    }


# ── Today's briefing ─────────────────────────────────────────────────────

def test_hard_sessions():
    assert is_hard({"sport_type": "Run", "target_pace_min": 4.0})
    assert is_hard({"sport_type": "Run", "target_hr_zone": 4})
    assert is_hard({"sport_type": "Run", "segments": [{"type": "work", "repetitions": 6, "distance_km": 0.4}]})
    assert not is_hard({"sport_type": "Run", "target_hr_zone": 2, "planned_distance_km": 12})
    # A fast warm-up alone doesn't make the session hard
    assert not is_hard({"sport_type": "Run", "segments": [{"type": "warmup", "target_pace_min": 4.0}]})


def test_recovery_classification():
    for recovery, form_pct, expected in [
        ({"readiness": {"level": "LOW"}}, 10, Recovery.LOW),
        ({"readiness": {"level": "HIGH"}, "hrv": {"status": "UNBALANCED"}}, 0, Recovery.STRAINED),
        ({"readiness": {"level": "HIGH"}}, 25, Recovery.STALE),
        ({"readiness": {"level": "MODERATE"}}, 0, Recovery.OK),
        (None, -35, Recovery.LOW),
        (None, 10, Recovery.GOOD),
        (None, None, Recovery.UNKNOWN),
    ]:
        assert classify(recovery, form_pct) == expected, (recovery, form_pct)


def test_what_today_holds():
    race = {"name": "City 10K"}
    assert day_of([{"sport_type": "Run", "target_pace_min": 4.0}], trained_today=True, race_today=race) == Day.RACE
    assert day_of([{"sport_type": "Run"}], trained_today=True, race_today=None) == Day.DONE
    assert day_of([{"sport_type": "Rest"}], trained_today=False, race_today=None) == Day.REST
    assert day_of([{"sport_type": "Run", "target_hr_zone": 5}], trained_today=False, race_today=None) == Day.HARD
    assert day_of([{"sport_type": "Run"}], trained_today=False, race_today=None) == Day.EASY
    assert day_of([], trained_today=False, race_today=None) == Day.FREE


# ── Stats response cache ─────────────────────────────────────────────────

def test_ttl_cache_expires_and_evicts_the_oldest(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(_ttl_cache, "time", SimpleNamespace(monotonic=lambda: now[0]))
    cache = TTLCache(maxsize=2, ttl_seconds=900)
    cache.set("a", 1)
    now[0] = 1.0
    cache.set("b", 2)
    now[0] = 2.0
    cache.set("a", 3)   # replacing a key never evicts
    assert (cache.get("a"), cache.get("b")) == (3, 2)
    now[0] = 3.0
    cache.set("c", 4)   # full: the oldest, b, goes
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == (3, None, 4)
    now[0] = 902.5
    assert (cache.get("a"), cache.get("c")) == (None, 4)
